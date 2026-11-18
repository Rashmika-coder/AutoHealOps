import pandas as pd

import analytics as an
from data_loader import load_events


def test_uptime_percentage(events):
    assert an.uptime_percentage(events) == 80.0  # 8 of 10 checks healthy


def test_uptime_percentage_without_data():
    assert an.uptime_percentage(pd.DataFrame(columns=["event", "status"])) is None


def test_downtime_is_failed_checks_times_interval(events):
    assert an.downtime_seconds(events, interval_s=10) == 20.0


def test_uptime_timeseries_buckets(events):
    ts = an.uptime_timeseries(events, "1min")
    assert list(ts.columns) == ["timestamp", "uptime_pct", "checks"]
    assert ts["checks"].sum() == 10
    assert ts["uptime_pct"].min() < 100  # the minute containing the outage


def test_failures_listed_newest_first(events):
    f = an.failures(events)
    assert len(f) == 3
    assert f["timestamp"].is_monotonic_decreasing


def test_failure_frequency_counts_all_failures(events):
    ff = an.failure_frequency(events, "1h")
    assert ff["failures"].sum() == 3


def test_failures_by_reason(events):
    br = an.failures_by_reason(events).set_index("reason")["count"]
    assert br["health check timeout"] == 2
    assert br["container exited"] == 1


def test_recovery_stats(events):
    s = an.recovery_stats(events)
    assert s["failures_detected"] == 3
    assert (s["restarts_attempted"], s["restarts_succeeded"]) == (4, 1)
    assert (s["rollbacks_attempted"], s["rollbacks_succeeded"]) == (2, 1)
    assert s["recoveries_verified"] == 2
    assert s["recoveries_failed"] == 1
    assert s["loop_halts"] == 1
    assert s["success_rate_pct"] == 50.0  # 2 verified of 4 finished
    assert s["mttr_seconds"] == 30.0


def test_recovery_stats_on_empty_log(tmp_path):
    s = an.recovery_stats(load_events(tmp_path / "missing.jsonl"))
    assert s["failures_detected"] == 0
    assert s["success_rate_pct"] is None
    assert s["mttr_seconds"] is None


def test_recovery_outcomes_skip_zero_rows(events):
    oc = an.recovery_outcomes(events).set_index("outcome")["count"]
    assert oc["Recovered"] == 2
    assert oc["Recovery failed"] == 1
    assert oc["Restart loop halted"] == 1


def test_recovery_method_summary(events):
    ms = an.recovery_method_summary(events)
    row = ms[(ms["method"] == "restart") & (ms["result"] == "failed")]
    assert row["count"].iloc[0] == 3


def test_recovery_actions_include_restart_and_rollback(events):
    a = an.recovery_actions(events)
    assert set(a["action"]) == {"restart", "rollback"}
    assert len(a) == 6


def test_container_status_history(events):
    h = an.container_status_history(events)
    assert set(h["container_status"]) == {"running", "exited"}


def test_deployment_summary():
    d = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-11-16T09:00Z", "2026-11-16T10:00Z",
                                     "2026-11-16T11:00Z", "2026-11-16T12:00Z"]),
        "version": ["v1", "v2", "v1", "v3"],
        "status": ["success", "rolled_back", "success", "failed"],
    })
    s = an.deployment_summary(d)
    assert s == {"total": 4, "successful": 2, "failed": 1, "rolled_back": 1,
                 "current_version": "v1"}


def test_deployment_summary_empty():
    assert an.deployment_summary(pd.DataFrame())["total"] == 0
