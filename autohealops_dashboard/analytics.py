"""Pure-pandas analytics over the monitoring logs (no Streamlit imports)."""
from __future__ import annotations

import pandas as pd

import config

_OK = {"success", "succeeded", "ok", "healthy", "true"}


def _is_ok(series: pd.Series) -> pd.Series:
    return series.astype("string").str.lower().isin(_OK)


def _of(events: pd.DataFrame, *names: str) -> pd.DataFrame:
    if events.empty:
        return events
    return events[events["event"].isin(names)]


# ---------------------------------------------------------------- health / uptime
def health_checks(events: pd.DataFrame) -> pd.DataFrame:
    """Health-check rows with a boolean ``healthy`` column."""
    hc = _of(events, config.EVENT_HEALTH).copy()
    if hc.empty:
        hc["healthy"] = pd.Series(dtype=bool)
        return hc
    hc["healthy"] = hc["status"].astype("string").str.lower().eq("healthy")
    return hc


def uptime_percentage(events: pd.DataFrame) -> float | None:
    """Share of health checks that passed, as a percentage (None if no data)."""
    hc = health_checks(events)
    if hc.empty:
        return None
    return round(float(hc["healthy"].mean()) * 100, 2)


def uptime_timeseries(events: pd.DataFrame, freq: str = "5min") -> pd.DataFrame:
    """Uptime % per time bucket. Columns: timestamp, uptime_pct, checks."""
    hc = health_checks(events)
    if hc.empty:
        return pd.DataFrame(columns=["timestamp", "uptime_pct", "checks"])
    grouped = hc.set_index("timestamp")["healthy"].resample(freq)
    out = pd.DataFrame({
        "uptime_pct": grouped.mean() * 100,
        "checks": grouped.count(),
    })
    out = out[out["checks"] > 0].reset_index()
    out["uptime_pct"] = out["uptime_pct"].round(2)
    return out


def response_time_series(events: pd.DataFrame) -> pd.DataFrame:
    hc = health_checks(events)
    hc = hc[hc["healthy"] & hc["response_time_ms"].notna()]
    return hc[["timestamp", "response_time_ms"]].reset_index(drop=True)


def container_status_history(events: pd.DataFrame) -> pd.DataFrame:
    """Container status observed on each health check."""
    hc = health_checks(events)
    hc = hc[hc["container_status"].notna()]
    return hc[["timestamp", "container_status", "version"]].reset_index(drop=True)


def downtime_seconds(events: pd.DataFrame, interval_s: float = 10) -> float:
    """Approximate downtime = failed checks x check interval."""
    hc = health_checks(events)
    if hc.empty:
        return 0.0
    return float((~hc["healthy"]).sum() * interval_s)


# ---------------------------------------------------------------- failures
def failures(events: pd.DataFrame) -> pd.DataFrame:
    """Detected failures, newest first."""
    f = _of(events, config.EVENT_FAILURE)
    cols = ["timestamp", "reason", "consecutive_failures", "http_status",
            "container_status", "version", "detail"]
    return f[cols].sort_values("timestamp", ascending=False).reset_index(drop=True)


def failure_frequency(events: pd.DataFrame, freq: str = "1h") -> pd.DataFrame:
    """Failures per time bucket, including empty buckets. Columns: timestamp, failures."""
    f = _of(events, config.EVENT_FAILURE)
    if f.empty:
        return pd.DataFrame(columns=["timestamp", "failures"])
    counts = f.set_index("timestamp").resample(freq).size()
    return counts.rename("failures").reset_index()


def failures_by_reason(events: pd.DataFrame) -> pd.DataFrame:
    f = _of(events, config.EVENT_FAILURE)
    if f.empty:
        return pd.DataFrame(columns=["reason", "count"])
    reasons = f["reason"].fillna("unspecified").astype(str)
    return reasons.value_counts().rename_axis("reason").reset_index(name="count")


# ---------------------------------------------------------------- recovery
def recovery_actions(events: pd.DataFrame) -> pd.DataFrame:
    """Every restart and rollback attempt, newest first."""
    a = _of(events, config.EVENT_RESTART, config.EVENT_ROLLBACK).copy()
    if a.empty:
        return pd.DataFrame(columns=["timestamp", "action", "result", "attempt",
                                     "from_version", "to_version", "detail"])
    a["action"] = a["event"]
    cols = ["timestamp", "action", "result", "attempt", "from_version",
            "to_version", "detail"]
    return a[cols].sort_values("timestamp", ascending=False).reset_index(drop=True)


def recovery_stats(events: pd.DataFrame) -> dict:
    """Headline recovery numbers for the KPI cards."""
    def count(name: str) -> int:
        return int(len(_of(events, name)))

    restarts = _of(events, config.EVENT_RESTART)
    rollbacks = _of(events, config.EVENT_ROLLBACK)
    verified = count(config.EVENT_VERIFIED)
    failed = count(config.EVENT_RECOVERY_FAILED)
    halted = count(config.EVENT_LOOP_HALT)

    finished = verified + failed + halted
    success_rate = round(verified / finished * 100, 1) if finished else None

    mttr = _of(events, config.EVENT_VERIFIED)["recovery_time_s"].dropna()
    return {
        "failures_detected": count(config.EVENT_FAILURE),
        "restarts_attempted": int(len(restarts)),
        "restarts_succeeded": int(_is_ok(restarts["result"]).sum()) if len(restarts) else 0,
        "rollbacks_attempted": int(len(rollbacks)),
        "rollbacks_succeeded": int(_is_ok(rollbacks["result"]).sum()) if len(rollbacks) else 0,
        "recoveries_verified": verified,
        "recoveries_failed": failed,
        "loop_halts": halted,
        "success_rate_pct": success_rate,
        "mttr_seconds": round(float(mttr.mean()), 1) if len(mttr) else None,
    }


def recovery_outcomes(events: pd.DataFrame) -> pd.DataFrame:
    """Outcome counts for the success/failure chart. Columns: outcome, count."""
    s = recovery_stats(events)
    rows = [
        ("Recovered", s["recoveries_verified"]),
        ("Recovery failed", s["recoveries_failed"]),
        ("Restart loop halted", s["loop_halts"]),
    ]
    return pd.DataFrame([r for r in rows if r[1] > 0], columns=["outcome", "count"])


def recovery_method_summary(events: pd.DataFrame) -> pd.DataFrame:
    """Success vs failure per recovery method. Columns: method, result, count."""
    a = recovery_actions(events)
    if a.empty:
        return pd.DataFrame(columns=["method", "result", "count"])
    a["result"] = a["result"].fillna("unknown").astype(str).str.lower()
    a["result"] = a["result"].where(~_is_ok(a["result"]), "success")
    out = a.groupby(["action", "result"]).size().reset_index(name="count")
    return out.rename(columns={"action": "method"})


def mttr_series(events: pd.DataFrame) -> pd.DataFrame:
    """Time-to-recovery for each verified recovery."""
    v = _of(events, config.EVENT_VERIFIED)
    v = v[v["recovery_time_s"].notna()]
    return v[["timestamp", "recovery_time_s"]].reset_index(drop=True)


def incident_timeline(events: pd.DataFrame) -> pd.DataFrame:
    """Chronological failure/recovery events (newest first) for the history table."""
    names = [config.EVENT_FAILURE, config.EVENT_RESTART, config.EVENT_ROLLBACK,
             config.EVENT_VERIFIED, config.EVENT_RECOVERY_FAILED, config.EVENT_LOOP_HALT]
    t = _of(events, *names)
    cols = ["timestamp", "event", "result", "attempt", "version", "from_version",
            "to_version", "recovery_time_s", "reason", "detail"]
    return t[cols].sort_values("timestamp", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------- deployments
def deployment_summary(deploys: pd.DataFrame) -> dict:
    if deploys.empty:
        return {"total": 0, "successful": 0, "failed": 0, "rolled_back": 0, "current_version": None}
    status = deploys["status"].astype("string").str.lower()
    current = deploys[status.isin(_OK)]
    return {
        "total": int(len(deploys)),
        "successful": int(status.isin(_OK).sum()),
        "failed": int(status.eq("failed").sum()),
        "rolled_back": int(status.eq("rolled_back").sum()),
        "current_version": (current.iloc[-1]["version"] if len(current) else None),
    }
