"""Render every dashboard page headlessly and fail on any exception."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import config
from generate_sample_data import build_history, write_jsonl

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["Overview", "Container status", "Deployment history", "Failures",
         "Recovery history", "Analytics"]


def _point_logs_at(monkeypatch, directory: Path) -> None:
    # config is already imported (and cached), so patch the attributes directly.
    monkeypatch.setattr(config, "RECOVERY_LOG", directory / "recovery_log.jsonl")
    monkeypatch.setattr(config, "DEPLOY_LOG", directory / "deployments.jsonl")


@pytest.fixture
def demo_logs(tmp_path, monkeypatch):
    events, deployments = build_history(hours=6)
    write_jsonl(tmp_path / "recovery_log.jsonl", events)
    write_jsonl(tmp_path / "deployments.jsonl", deployments)
    _point_logs_at(monkeypatch, tmp_path)
    return tmp_path


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_data(demo_logs, page):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_with_empty_logs(tmp_path, monkeypatch, page):
    _point_logs_at(monkeypatch, tmp_path)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
