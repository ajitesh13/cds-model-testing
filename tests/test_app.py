import json
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from thalamus.adapters.base import Completion
from thalamus.store import Store

GOOD = json.dumps({
    "question_type": "lookup", "answer": "AFI 3 cm.", "key_caveat": "Single measurement.", "details": ["On 2023-05-15."],
    "claims": [{"text": "AFI", "type": "documented", "cites": ["E7.IMAGING.1"], "values": ["3 cm"]}],
    "conflicts": [], "not_documented": []})


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_USERNAME", "tester")
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENABLED_CONFIGS", "opus-high")
    monkeypatch.delenv("MODEL_SELECTION", raising=False)
    st.cache_resource.clear()  # Store path is cached per process
    return tmp_path


def app():
    return AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=30)


def login(at):
    at.text_input[0].set_value("tester")
    at.text_input[1].set_value("s3cret")
    at.button[0].click().run()


def test_refuses_without_credentials(monkeypatch):
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    at = app().run()
    assert any("must be set" in e.value for e in at.error)
    assert not at.text_area


def test_login_required_and_wrong_password(env, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    at = app().run()
    assert not at.text_area and at.button[0].label == "Log in"
    at.text_input[0].set_value("tester")
    at.text_input[1].set_value("wrong")
    at.button[0].click().run()
    assert any("Incorrect" in e.value for e in at.error) and not at.text_area


def test_ask_rate_blind(env, monkeypatch):
    class Fake:
        def complete(self, cfg, *a, **k):
            return Completion(GOOD, cfg.model + "-d", 100, 10, 0, 5, {})

    monkeypatch.setattr("thalamus.pipeline.get_adapter", lambda p: Fake())
    at = app().run()
    login(at)
    assert at.text_area  # question box visible after login
    at.text_area[0].set_value("What was the AFI?")
    at.button[1].click().run()  # [Log in gone] -> buttons: logout, ask
    page = " ".join(m.value for m in at.markdown)
    assert "Verified" in page and "AFI 3 cm." in page
    assert not any("claude-opus" in c.value for c in at.caption)  # model hidden in blind mode
    runs = Store(env / "thalamus.db").list_runs()
    assert len(runs) == 1 and runs[0]["source"] == "web" and runs[0]["status"] == "verified"
    # rate it
    at.radio[0].set_value("minor_error")
    next(b for b in at.button if b.label == "Submit rating").click().run()
    ratings = Store(env / "thalamus.db").list_ratings()
    assert len(ratings) == 1 and ratings[0]["grade"] == "minor_error" and ratings[0]["run_id"] == runs[0]["run_id"]


def test_error_run_is_friendly_and_stored(env, monkeypatch):
    class Boom:
        def complete(self, *a, **k):
            raise RuntimeError("secret internals")

    monkeypatch.setattr("thalamus.pipeline.get_adapter", lambda p: Boom())
    at = app().run()
    login(at)
    at.text_area[0].set_value("anything at all")
    at.button[1].click().run()
    assert any("could not get an answer" in e.value for e in at.error)
    assert not any("secret internals" in e.value for e in at.error)
    assert Store(env / "thalamus.db").list_runs()[0]["status"] == "error"
