"""Read the logs written by the monitoring engine and probe live status."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pandas as pd
import requests

import config


def _read_jsonl(path: Path, columns: list[str]) -> pd.DataFrame:
    """Read a JSON Lines file tolerantly.

    * Missing file  -> empty frame with the expected columns.
    * Blank lines   -> ignored.
    * Corrupt lines -> skipped and counted in ``df.attrs["skipped"]``
      (a half-written line is normal while the monitor is appending).
    """
    path = Path(path)
    rows: list[dict] = []
    skipped = 0
    if path.exists():
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    skipped += 1

    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    # Keep unknown extra columns after the known ones.
    extras = [c for c in df.columns if c not in columns]
    df = df[columns + extras]

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    bad_ts = int(df["timestamp"].isna().sum())
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    df.attrs["skipped"] = skipped + bad_ts
    return df


def load_events(path: Path | str | None = None) -> pd.DataFrame:
    """Recovery/health events from the monitoring engine."""
    df = _read_jsonl(path or config.RECOVERY_LOG, config.EVENT_COLUMNS)
    for col in ("response_time_ms", "recovery_time_s", "http_status", "attempt",
                "consecutive_failures"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def load_deployments(path: Path | str | None = None) -> pd.DataFrame:
    """Deployment history written by the CI/CD pipeline."""
    return _read_jsonl(path or config.DEPLOY_LOG, config.DEPLOY_COLUMNS)


def filter_window(df: pd.DataFrame, hours: float | None) -> pd.DataFrame:
    """Keep rows newer than ``hours`` ago. ``None`` keeps everything."""
    if hours is None or df.empty:
        return df
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
    out = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    out.attrs.update(df.attrs)
    return out


def check_live_health(url: str | None = None, timeout: float | None = None) -> dict:
    """Call the Flask /health endpoint once.

    Returns a dict with ``state`` in {"healthy", "unhealthy", "unreachable"}.
    """
    url = url or config.HEALTH_ENDPOINT
    timeout = timeout or config.HEALTH_TIMEOUT_S
    started = time.perf_counter()
    result = {
        "state": "unreachable",
        "http_status": None,
        "response_time_ms": None,
        "version": None,
        "message": "",
        "checked_at": pd.Timestamp.now(tz="UTC"),
    }
    try:
        resp = requests.get(url, timeout=timeout)
        result["response_time_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["http_status"] = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            result["version"] = body.get("version")
            result["message"] = str(body.get("status", ""))
        result["state"] = "healthy" if resp.status_code == 200 else "unhealthy"
    except requests.Timeout:
        result["state"] = "unreachable"
        result["message"] = f"timed out after {timeout:g}s"
    except requests.RequestException as exc:
        result["state"] = "unreachable"
        result["message"] = type(exc).__name__
    return result


def get_container_status(name: str | None = None) -> dict:
    """Inspect the app container via the Docker CLI.

    Works when the dashboard host can run ``docker`` (mount
    /var/run/docker.sock when running the dashboard in a container).
    ``available`` is False when Docker cannot be reached.
    """
    name = name or config.CONTAINER_NAME
    info = {
        "name": name, "available": False, "status": "unknown", "running": False,
        "image": None, "started_at": None, "restart_count": None, "error": "",
    }
    try:
        proc = subprocess.run(
            ["docker", "inspect", name],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except FileNotFoundError:
        info["error"] = "docker CLI not found"
        return info
    except subprocess.TimeoutExpired:
        info["error"] = "docker inspect timed out"
        return info

    if proc.returncode != 0:
        info["available"] = True  # Docker answered, the container just isn't there.
        info["status"] = "not found"
        info["error"] = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ""
        return info

    try:
        data = json.loads(proc.stdout)[0]
    except (json.JSONDecodeError, IndexError):
        info["error"] = "unexpected docker inspect output"
        return info

    state = data.get("State", {})
    info.update(
        available=True,
        status=state.get("Status", "unknown"),
        running=bool(state.get("Running")),
        image=data.get("Config", {}).get("Image"),
        started_at=state.get("StartedAt"),
        restart_count=data.get("RestartCount"),
    )
    return info
