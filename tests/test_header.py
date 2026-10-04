from datetime import date

from thalamus.serialize import HeaderData, compute_header, render_header, serialize


def test_ages(patient):
    ages = {i: a for i, _, a in compute_header(patient).ages}
    assert ages[1] == 42 and ages[8] == 45
    assert ages[7] == 45 and ages[4] == 45 and ages[3] == 42


def test_anchor_table(patient):
    d = compute_header(patient)
    assert d.pregnancy_encounters == [4, 5, 6, 7, 8]
    assert len(d.anchors) == 2
    assert (d.anchors[0].date, d.anchors[0].weeks) == (date(2023, 1, 15), 17)
    assert (d.anchors[1].date, d.anchors[1].weeks) == (date(2023, 2, 15), 17)
    assert [g for _, g in d.ga["A"]] == ["17w0d", "17w0d", "21w3d", "34w1d", "38w4d"]
    assert [g for _, g in d.ga["B"]] == ["12w4d", "12w4d", "17w0d", "29w5d", "34w1d"]


def test_header_text(patient):
    h = serialize(patient).header
    assert "COMPUTED BY CODE" in h and "DATING UNCERTAIN" in h
    assert "approximate, no date of birth in record" in h
    assert "Anchor A: E4 17w0d | E5 17w0d | E6 21w3d | E7 34w1d | E8 38w4d" in h
    assert "Anchor B: E4 12w4d | E5 12w4d | E6 17w0d | E7 29w5d | E8 34w1d" in h
    assert "Prenatal vitamin 1 tablet daily" in h and "Allergies (profile): NKDA" in h
    assert "Home Medications:" not in h


def test_lmp_dating(patient):
    p = patient.model_copy(deep=True)
    e4 = next(e for e in p.encounters if e.index == 4)
    e4.sections["HPI"].append("LMP 2022-09-25 per patient.")
    d = compute_header(p)
    assert d.dating and "LMP 2022-09-25" in d.ga
    assert [g for _, g in d.ga["LMP 2022-09-25"]][0] == "16w0d"
    assert "DATING UNCERTAIN" not in render_header(d)
