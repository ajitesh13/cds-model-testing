import pytest

from thalamus.answer import Answer, Claim, Conflict
from thalamus.serialize import serialize
from thalamus.verify import contains, format_checks, normalize, verify_citations


@pytest.fixture(scope="module")
def ser(patient):
    return serialize(patient)


def ans(*claims, **kw):
    base = dict(question_type="lookup", answer="x", key_caveat=None, details=[], claims=list(claims),
                conflicts=[], not_documented=[])
    return Answer(**{**base, **kw})


def doc(cites, values, text="claim"):
    return Claim(text=text, type="documented", cites=cites, values=values)


def comp(values):
    return Claim(text="computed", type="computed", values=values)


BAD = {
    "wrong value": doc(["E7.IMAGING.1"], ["5 cm"]),
    "nonexistent row": doc(["E9.HPI.1"], ["x"]),
    "wrong date": doc(["E7.IMAGING.1"], ["2023-05-16"]),
    "wrong department": doc(["E7.IMAGING.1"], ["Urogynecology"]),
    "wrong attending": doc(["E7.IMAGING.1"], ["Dr. Sarah Chen"]),
    "value in uncited row": doc(["E7.PHYSICAL_EXAM.1"], ["122/78 mmHg"]),
    "invented drug": doc(["E8.MEDICATIONS.2"], ["metformin 500 mg"]),
    "invented allergy": doc(["P.ALLERGIES.1"], ["penicillin allergy"]),
    "no cites": doc([], ["3 cm"]),
    "partial number": doc(["E7.IMAGING.1"], ["13 cm"]),
    "computed GA absent": comp(["38w5d"]),
    "computed other anchor wrong": comp(["34w2d"]),
    "computed age absent": comp(["46"]),
    "computed no values": comp([]),
    "one cite missing among several": doc(["E7.IMAGING.1", "E7.IMAGING.9"], ["3 cm"]),
}


@pytest.mark.parametrize("name", BAD)
def test_planted_errors_flagged(ser, name):
    v = verify_citations(ans(BAD[name]), ser.rows, ser.header)
    assert not v.ok and v.failures, name


def test_only_bad_claim_flagged(ser):
    v = verify_citations(ans(doc(["E7.IMAGING.1"], ["3 cm"]), doc(["E7.IMAGING.1"], ["5 cm"])), ser.rows, ser.header)
    assert [f.claim_index for f in v.failures] == [1]
    assert "5 cm" in v.retry_message()


def test_correct_answers_pass(ser):
    good = [
        doc(["E7.IMAGING.1"], ["amniotic fluid index (AFI) of 3 cm"]),
        doc(["E7.IMAGING.1"], ["3cm", "2023-05-15"]),  # date comes from the encounter heading
        doc(["E7.IMAGING.1"], ["Dr. Jennifer Park", "Obstetrics & Gynecology"]),
        doc(["E8.VITALS.1"], ["blood pressure is 122/78 mmHg."]),
        doc(["P.ALLERGIES.1"], ["nkda"]),
        comp(["34w1d", "38w4d"]),
        comp(["45"]),
        Claim(text="inferred", type="inferred", cites=["E9.X.1"], values=["nonsense"]),
        Claim(text="opinion", type="opinion", values=["nonsense"]),
    ]
    for c in good:
        assert verify_citations(ans(c), ser.rows, ser.header).ok, c
    assert verify_citations(ans(*good), ser.rows, ser.header).ok


def test_normalize():
    assert normalize("  AFI of 3  cm. ") == normalize("afi of 3cm")
    assert normalize("Patient’s “X” – y") == "patient's \"x\" - y"
    assert contains("a 13 cm mass", "3 cm") is False
    assert contains("an AFI of 3 cm.", "3cm")


def test_format_checks():
    ok = ans()
    assert all(c["passed"] for c in format_checks(ok))
    long = ans(details=["word " * 61])
    assert not next(c for c in format_checks(long) if c["check"] == "word_cap")["passed"]
    assert next(c for c in format_checks(ans(question_type="synthesis", details=["word " * 61])) if c["check"] == "word_cap")["passed"]
    assert not next(c for c in format_checks(ans(not_documented=["x"])) if c["check"] == "caveat_present")["passed"]
    assert next(c for c in format_checks(ans(conflicts=[Conflict(topic="t", rows=[])], key_caveat="c")) if c["check"] == "caveat_present")["passed"]
    assert not next(c for c in format_checks(ans(answer=" ")) if c["check"] == "answer_non_empty")["passed"]
