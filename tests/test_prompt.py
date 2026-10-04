import hashlib

from thalamus.prompt import SYSTEM_PROMPT_PATH, load_system, prompt_version, question_block, record_block
from thalamus.serialize import serialize


def test_prompt_version():
    assert prompt_version() == hashlib.sha256(SYSTEM_PROMPT_PATH.read_bytes()).hexdigest()[:12]
    assert len(prompt_version()) == 12


def test_system_prompt_text():
    s = load_system()
    assert s.startswith("You are a clinical decision support assistant for obstetrics and gynecology.")
    assert s.rstrip().endswith("14. Respond with JSON only, matching the provided schema.")


def test_blocks(patient):
    ser = serialize(patient)
    r = record_block(ser.text)
    assert r.startswith("PATIENT RECORD\n=== COMPUTED BY CODE")
    assert record_block(ser.text) == r  # byte-identical for every question
    assert question_block("  What is the AFI? ") == "DOCTOR'S QUESTION: What is the AFI?"
