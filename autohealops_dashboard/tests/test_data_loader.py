import json
from unittest.mock import MagicMock, patch

import pandas as pd
import requests

import config
from data_loader import (check_live_health, filter_window, get_container_status,
                         load_deployments, load_events)


def test_missing_file_gives_empty_frame_with_columns(tmp_path):
    df = load_events(tmp_path / "nope.jsonl")
    assert df.empty
    assert set(config.EVENT_COLUMNS) <= set(df.columns)


def test_corrupt_and_blank_lines_are_skipped(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text(
        json.dumps({"timestamp": "2026-11-16T10:00:00Z", "event": "health_check"}) + "\n"
        "\n"
        '{"timestamp": "2026-11-16T10:00:10Z", "event": "hea\n'      # half-written line
        "[1, 2, 3]\n"                                               # valid JSON, wrong shape
        + json.dumps({"event": "health_check"}) + "\n"              # no timestamp
        + json.dumps({"timestamp": "2026-11-16T10:00:20Z", "event": "health_check"}) + "\n",
        encoding="utf-8",
    )
    df = load_events(p)
    assert len(df) == 2
    assert df.attrs["skipped"] == 3


def test_events_sorted_and_timezone_aware(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text(
        json.dumps({"timestamp": "2026-11-16T10:00:20Z", "event": "b"}) + "\n"
        + json.dumps({"timestamp": "2026-11-16T10:00:10Z", "event": "a"}) + "\n",
        encoding="utf-8",
    )
    df = load_events(p)
    assert list(df["event"]) == ["a", "b"]
    assert str(df["timestamp"].dt.tz) == "UTC"


def test_numeric_columns_are_coerced(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text(json.dumps({"timestamp": "2026-11-16T10:00:00Z", "event": "health_check",
                             "response_time_ms": "12.5"}) + "\n", encoding="utf-8")
    assert load_events(p)["response_time_ms"].iloc[0] == 12.5


def test_load_deployments(tmp_path):
    p = tmp_path / "deployments.jsonl"
    p.write_text(json.dumps({"timestamp": "2026-11-16T10:00:00Z", "version": "v1",
                             "status": "success"}) + "\n", encoding="utf-8")
    df = load_deployments(p)
    assert df["version"].iloc[0] == "v1"
    assert "commit" in df.columns


def test_filter_window_keeps_recent_rows():
    now = pd.Timestamp.now(tz="UTC")
    df = pd.DataFrame({"timestamp": [now - pd.Timedelta(hours=5), now - pd.Timedelta(minutes=10)],
                       "event": ["old", "new"]})
    assert list(filter_window(df, 1)["event"]) == ["new"]
    assert len(filter_window(df, None)) == 2


# ---- live probes are mocked: no network or Docker needed -------------------
def test_live_health_healthy():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"status": "healthy", "version": "v2"}
    with patch("data_loader.requests.get", return_value=resp):
        r = check_live_health("http://app/health")
    assert r["state"] == "healthy"
    assert r["version"] == "v2"
    assert r["http_status"] == 200


def test_live_health_unhealthy_on_500():
    resp = MagicMock(status_code=500)
    resp.json.side_effect = ValueError
    with patch("data_loader.requests.get", return_value=resp):
        assert check_live_health("http://app/health")["state"] == "unhealthy"


def test_live_health_unreachable_on_timeout_and_connection_error():
    with patch("data_loader.requests.get", side_effect=requests.Timeout):
        assert check_live_health("http://app/health")["state"] == "unreachable"
    with patch("data_loader.requests.get", side_effect=requests.ConnectionError):
        assert check_live_health("http://app/health")["state"] == "unreachable"


def test_container_status_running():
    out = json.dumps([{"State": {"Status": "running", "Running": True,
                                 "StartedAt": "2026-11-16T10:00:00Z"},
                       "Config": {"Image": "autohealops-app:v1"}, "RestartCount": 2}])
    proc = MagicMock(returncode=0, stdout=out, stderr="")
    with patch("data_loader.subprocess.run", return_value=proc):
        info = get_container_status("app")
    assert info["running"] is True
    assert info["status"] == "running"
    assert info["restart_count"] == 2
    assert info["image"] == "autohealops-app:v1"


def test_container_status_not_found():
    proc = MagicMock(returncode=1, stdout="", stderr="Error: No such object: app")
    with patch("data_loader.subprocess.run", return_value=proc):
        info = get_container_status("app")
    assert info["available"] is True
    assert info["status"] == "not found"


def test_container_status_without_docker_cli():
    with patch("data_loader.subprocess.run", side_effect=FileNotFoundError):
        info = get_container_status("app")
    assert info["available"] is False
    assert "docker" in info["error"]
