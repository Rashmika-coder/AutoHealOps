import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_loader import load_events  # noqa: E402


def _ts(minute: int, second: int = 0) -> str:
    total = minute * 60 + second
    return f"2026-11-16T10:{total // 60:02d}:{total % 60:02d}Z"


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def sample_rows() -> list[dict]:
    """10 health checks (8 healthy, 2 unhealthy) and three incidents.

    A: restart succeeds, recovered in 20s
    B: restart fails, rollback succeeds, recovered in 40s
    C: 2 restarts fail, rollback fails, restart loop halted
    """
    rows = []
    for i in range(10):
        healthy = i not in (4, 5)
        rows.append({"timestamp": _ts(0, i * 10), "event": "health_check",
                     "status": "healthy" if healthy else "unhealthy",
                     "http_status": 200 if healthy else None,
                     "response_time_ms": 20 + i if healthy else None,
                     "container_status": "running" if healthy else "exited", "version": "v1"})
    rows += [
        {"timestamp": _ts(1), "event": "failure_detected", "reason": "container exited",
         "consecutive_failures": 3},
        {"timestamp": _ts(1, 5), "event": "restart", "result": "success", "attempt": 1},
        {"timestamp": _ts(1, 20), "event": "recovery_verified", "result": "success",
         "recovery_time_s": 20},
        {"timestamp": _ts(30), "event": "failure_detected", "reason": "health check timeout",
         "consecutive_failures": 3},
        {"timestamp": _ts(30, 5), "event": "restart", "result": "failed", "attempt": 1},
        {"timestamp": _ts(30, 25), "event": "rollback", "result": "success",
         "from_version": "v2", "to_version": "v1"},
        {"timestamp": _ts(30, 40), "event": "recovery_verified", "result": "success",
         "recovery_time_s": 40},
        {"timestamp": _ts(50), "event": "failure_detected", "reason": "health check timeout",
         "consecutive_failures": 3},
        {"timestamp": _ts(50, 5), "event": "restart", "result": "failed", "attempt": 1},
        {"timestamp": _ts(50, 25), "event": "restart", "result": "failed", "attempt": 2},
        {"timestamp": _ts(50, 45), "event": "rollback", "result": "failed",
         "from_version": "v3", "to_version": "v1"},
        {"timestamp": _ts(51), "event": "restart_loop_halted", "result": "failed", "attempt": 2},
        {"timestamp": _ts(51, 1), "event": "recovery_failed", "result": "failed"},
    ]
    return rows


@pytest.fixture
def events(tmp_path, sample_rows):
    return load_events(write_jsonl(tmp_path / "recovery_log.jsonl", sample_rows))
