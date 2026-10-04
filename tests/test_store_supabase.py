import json
import urllib.request

import pytest

from thalamus.store import Store, SupabaseStore, make_store


class FakeResp:
    def __init__(self, body=b""):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def sb(tmp_path):
    return SupabaseStore("https://x.supabase.co/", "KEY", fallback=Store(tmp_path / "fb.db"))


def test_insert_posts_row_with_parsed_json(sb, monkeypatch):
    seen = {}

    def fake(req, timeout):
        seen.update(url=req.full_url, method=req.get_method(), body=json.loads(req.data), h=dict(req.header_items()))
        return FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    rid = sb.insert_run(question_text="q", status="verified", answer_json='{"a": 1}', client_ip="1.2.3.4", patient="p")
    assert seen["url"] == "https://x.supabase.co/rest/v1/thalamus_harness_runs" and seen["method"] == "POST"
    assert seen["body"]["id"] == rid and "run_id" not in seen["body"]
    assert seen["body"]["answer_json"] == {"a": 1} and seen["body"]["client_ip"] == "1.2.3.4"
    assert seen["h"]["Authorization"] == "Bearer KEY"
    assert sb.fallback.list_runs() == []


def test_write_failure_falls_back_to_sqlite(sb, monkeypatch):
    def boom(req, timeout):
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    rid = sb.insert_run(question_text="q", status="error", client_ip="1.2.3.4")  # extras dropped by SQLite
    assert sb.fallback.get_run(rid)["status"] == "error"


def test_unknown_column_rejected(sb):
    with pytest.raises(ValueError):
        sb.insert_run(question_text="q", status="error", nope=1)


def test_list_runs_filters_pages_and_maps(sb, monkeypatch):
    urls = []
    pages = [[{"id": f"i{n}", "answer_json": {"a": n}} for n in range(1000)], [{"id": "last", "answer_json": None}]]

    def fake(req, timeout):
        urls.append(req.full_url)
        return FakeResp(json.dumps(pages[len(urls) - 1]).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    runs = sb.list_runs("s 1")
    assert len(runs) == 1001 and runs[0]["run_id"] == "i0" and runs[0]["answer_json"] == '{"a": 0}'
    assert runs[-1]["answer_json"] is None
    assert "session_id=eq.s%201" in urls[0] and "offset=1000" in urls[1]


def test_make_store_picks_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert isinstance(make_store(), Store)
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    assert isinstance(make_store(), Store)  # key missing
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    assert isinstance(make_store(), SupabaseStore)
