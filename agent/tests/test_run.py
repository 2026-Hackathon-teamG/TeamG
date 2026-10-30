"""
/run 엔드포인트와 실행 흐름 테스트. 실제 LLM과 gateway는 부르지 않는다.

실행:
    cd agent
    pytest tests/test_run.py
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import llm_agent, main
from app.replay import latest_run_file


def _write_run(path, *, completed: bool) -> None:
    lines = [{"type": "meta", "run_id": path.stem, "mode": "live", "target": "http://gateway:8000"}]
    if completed:
        lines.append({"type": "end", "run_id": path.stem, "summary": "끝"})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


@pytest.fixture
def client():
    return TestClient(main.app)


# ---------- 재생할 녹화 고르기 ----------

def test_latest_run_skips_incomplete(tmp_path):
    _write_run(tmp_path / "20261030T100000Z.jsonl", completed=True)
    _write_run(tmp_path / "20261030T110000Z.jsonl", completed=False)   # 중간에 실패한 live run
    assert latest_run_file(str(tmp_path)) == "20261030T100000Z.jsonl"


def test_latest_run_picks_newest(tmp_path):
    _write_run(tmp_path / "20261030T100000Z.jsonl", completed=True)
    _write_run(tmp_path / "20261030T120000Z.jsonl", completed=True)
    assert latest_run_file(str(tmp_path)) == "20261030T120000Z.jsonl"


def test_latest_run_none(tmp_path):
    assert latest_run_file(str(tmp_path)) is None
    assert latest_run_file(str(tmp_path / "missing")) is None


# ---------- /run ----------

def test_replay_without_recording_is_404(client, monkeypatch):
    monkeypatch.setattr(main, "latest_run_file", lambda: None)
    r = client.post("/run", json={"mode": "replay"})
    assert r.status_code == 404


def test_replay_defaults_to_latest_and_returns_at_once(client, monkeypatch, tmp_path):
    run_file = tmp_path / "20261030T100000Z.jsonl"
    _write_run(run_file, completed=True)
    monkeypatch.setattr(main, "latest_run_file", lambda: str(run_file))
    started = []
    monkeypatch.setattr(main, "_start", lambda job, label: started.append(label))

    r = client.post("/run", json={"mode": "replay"})
    assert r.status_code == 202
    assert r.json()["run_file"] == str(run_file)
    assert started == ["replay"]


def test_busy_is_409(client, monkeypatch, tmp_path):
    run_file = tmp_path / "20261030T100000Z.jsonl"
    _write_run(run_file, completed=True)
    monkeypatch.setattr(main, "latest_run_file", lambda: str(run_file))
    assert main._running.acquire(blocking=False)
    try:
        assert client.post("/run", json={"mode": "replay"}).status_code == 409
    finally:
        main._running.release()


def test_live_without_api_key_is_400(client, monkeypatch):
    monkeypatch.setattr(main, "ANTHROPIC_API_KEY", "")
    assert client.post("/run", json={"mode": "live"}).status_code == 400


def test_unknown_mode_is_400(client):
    assert client.post("/run", json={"mode": "x"}).status_code == 400


# ---------- live 실행 흐름 ----------

class _FakeRecorder:
    def __init__(self):
        self.run_id = "test"
        self.outcomes = []
        self.ended = False

    def write_meta(self, **_):
        pass

    def write_outcome(self, outcome):
        self.outcomes.append(outcome)

    def write_end(self, summary):
        self.ended = True


@pytest.fixture
def live(monkeypatch):
    """anthropic 클라이언트, Recorder, http_get을 가짜로 바꾼다."""
    calls, notes, recorder = [], [], _FakeRecorder()

    def fake_http_get(client, ip_rotator, path, note, headers=None):
        notes.append(note)
        return SimpleNamespace(error=None, http_status=200, response_text="")

    monkeypatch.setattr(llm_agent, "Recorder", lambda: recorder)
    monkeypatch.setattr(llm_agent, "http_get", fake_http_get)
    return SimpleNamespace(calls=calls, notes=notes, recorder=recorder, monkeypatch=monkeypatch)


def _fake_anthropic(create):
    return lambda **_: SimpleNamespace(messages=SimpleNamespace(create=create))


def test_live_does_not_send_temperature(live):
    def create(**kwargs):
        live.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="요약")])

    live.monkeypatch.setattr(llm_agent.anthropic, "Anthropic", _fake_anthropic(create))
    result = llm_agent.run_live()

    assert "temperature" not in live.calls[0]
    assert result["final_text"] == "요약"
    assert live.notes == ["__END__"]
    assert live.recorder.ended


def test_live_sends_end_even_on_failure(live):
    def create(**kwargs):
        raise RuntimeError("API 오류")

    live.monkeypatch.setattr(llm_agent.anthropic, "Anthropic", _fake_anthropic(create))
    with pytest.raises(RuntimeError):
        llm_agent.run_live()

    assert live.notes == ["__END__"]       # 관제 화면이 "실행 중"에 멈추지 않게
    assert not live.recorder.ended         # 실패한 run은 replay 대상이 되지 않게
