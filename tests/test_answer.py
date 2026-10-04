import json

import pytest

from thalamus.answer import AnswerParseError, parse_answer

GOOD = {
    "question_type": "lookup", "answer": "3 cm.", "key_caveat": None, "details": [],
    "claims": [{"text": "AFI 3 cm", "type": "documented", "cites": ["E7.IMAGING.1"], "values": ["3 cm"]}],
    "conflicts": [], "not_documented": [],
}


def test_plain_json():
    a = parse_answer(json.dumps(GOOD))
    assert a.claims[0].cites == ["E7.IMAGING.1"]


def test_code_fence():
    assert parse_answer("```json\n" + json.dumps(GOOD) + "\n```").answer == "3 cm."
    assert parse_answer("```\n" + json.dumps(GOOD) + "\n```").answer == "3 cm."


def test_claim_defaults():
    d = {**GOOD, "claims": [{"text": "x", "type": "opinion"}]}
    c = parse_answer(json.dumps(d)).claims[0]
    assert c.cites == [] and c.values == []


@pytest.mark.parametrize("bad", ["not json", "{}", json.dumps({**GOOD, "question_type": "other"}),
                                 json.dumps({k: v for k, v in GOOD.items() if k != "key_caveat"})])
def test_invalid(bad):
    with pytest.raises(AnswerParseError):
        parse_answer(bad)
