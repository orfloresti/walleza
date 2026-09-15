"""Design D124 / D45 / D51: `app.scheduler.handler`'s three-pass wiring.

Unit-level only — Pass A/B/C's own behaviour is covered by
`tests/recurring/` and `tests/ocr/test_cleanup.py` respectively. This test
just proves the handler calls all three in order on one session and
surfaces all three summary dicts, without touching a real database or S3.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app import scheduler
from app.ocr import cleanup as ocr_cleanup
from app.recurring import generation


def test_handler_runs_generation_reminders_then_ocr_cleanup(monkeypatch) -> None:
    calls: list[str] = []

    fake_db = MagicMock()
    fake_session_local = MagicMock(return_value=fake_db)
    monkeypatch.setattr(scheduler, "SessionLocal", fake_session_local)

    def fake_run(db, *, today):
        assert db is fake_db
        calls.append("generation")
        return {"due": 0, "generated": 0, "paused": 0, "locked": 0, "errors": 0}

    def fake_run_reminders(db, *, today):
        assert db is fake_db
        calls.append("reminders")
        return {"due": 0, "sent": 0, "paused": 0, "locked": 0, "skipped": 0, "errors": 0}

    def fake_sweep(db, *, now):
        assert db is fake_db
        calls.append("ocr_cleanup")
        return {"deleted": 3}

    monkeypatch.setattr(generation, "run", fake_run)
    monkeypatch.setattr(generation, "run_reminders", fake_run_reminders)
    monkeypatch.setattr(ocr_cleanup, "sweep_abandoned_drafts", fake_sweep)

    result = scheduler.handler({}, None)

    assert calls == ["generation", "reminders", "ocr_cleanup"]
    assert result == {
        "generation": {"due": 0, "generated": 0, "paused": 0, "locked": 0, "errors": 0},
        "reminders": {
            "due": 0,
            "sent": 0,
            "paused": 0,
            "locked": 0,
            "skipped": 0,
            "errors": 0,
        },
        "ocr_cleanup": {"deleted": 3},
    }
    fake_db.close.assert_called_once()
