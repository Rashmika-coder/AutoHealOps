"""Generate realistic demo logs so the dashboard works before Persons 1-3 finish.

    python generate_sample_data.py                 # 6 hours of history
    python generate_sample_data.py --hours 24
    python generate_sample_data.py --live          # keep appending a check every 10s

The output follows the log contract in README.md, so when the real monitoring
engine starts writing the same format the dashboard needs no changes.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHECK_INTERVAL_S = 10
DETECT_AFTER_FAILURES = 3
RESTART_COST_S = 15
ROLLBACK_COST_S = 25
MANUAL_FIX_S = 300  # how long an unrecovered incident stays down

# (fraction of window the incident starts at, kind, recovery steps)
INCIDENTS = [
    (0.17, "crash", [("restart", "success")]),
    (0.42, "hang", [("restart", "failed"), ("restart", "failed"), ("rollback", "success")]),
    (0.67, "crash", [("restart", "success")]),
    (0.84, "hang", [("restart", "failed"), ("restart", "failed"),
                    ("restart", "failed"), ("rollback", "failed")]),
]


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _health_row(ts, healthy, rng, container_status, version, reason=None):
    if healthy:
        rt = max(5.0, rng.gauss(18, 4))
        if rng.random() < 0.02:
            rt = rng.uniform(120, 300)
        return {"timestamp": _iso(ts), "event": "health_check", "status": "healthy",
                "http_status": 200, "response_time_ms": round(rt, 1),
                "container_status": container_status, "version": version}
    return {"timestamp": _iso(ts), "event": "health_check", "status": "unhealthy",
            "http_status": None, "response_time_ms": None,
            "container_status": container_status, "version": version, "reason": reason}


def build_history(hours: float = 6, seed: int = 7, end: datetime | None = None):
    rng = random.Random(seed)
    end = end or datetime.now(timezone.utc)
    total_s = hours * 3600
    start = end - timedelta(seconds=total_s)

    events: list[dict] = []
    down: list[tuple[float, float, str]] = []  # (start_off, end_off, kind)
    rollback_done_off: float | None = None

    for frac, kind, steps in INCIDENTS:
        s0 = frac * total_s
        reason = ("container exited unexpectedly" if kind == "crash"
                  else "health check timeout (app unresponsive)")
        cursor = s0 + CHECK_INTERVAL_S * (DETECT_AFTER_FAILURES - 1)
        events.append({"timestamp": _iso(start + timedelta(seconds=cursor)),
                       "event": "failure_detected", "reason": reason,
                       "consecutive_failures": DETECT_AFTER_FAILURES,
                       "container_status": "exited" if kind == "crash" else "running"})
        restart_attempt = 0
        recovered = False
        for method, result in steps:
            cursor += 3
            row = {"timestamp": _iso(start + timedelta(seconds=cursor)),
                   "event": method, "result": result}
            if method == "restart":
                restart_attempt += 1
                row["attempt"] = restart_attempt
                row["detail"] = "docker restart autohealops-app"
                cursor += RESTART_COST_S
            else:
                v_from, v_to = ("v2", "v1") if frac < 0.8 else ("v3", "v1")
                row.update(from_version=v_from, to_version=v_to,
                           detail=f"redeploy previous stable image {v_to}")
                cursor += ROLLBACK_COST_S
                if result == "success":
                    rollback_done_off = cursor
            events.append(row)
            recovered = result == "success"

        if recovered:
            events.append({"timestamp": _iso(start + timedelta(seconds=cursor)),
                           "event": "recovery_verified", "result": "success",
                           "recovery_time_s": round(cursor - s0, 1),
                           "detail": "3 consecutive healthy checks"})
            down.append((s0, cursor, kind))
        else:
            events.append({"timestamp": _iso(start + timedelta(seconds=cursor)),
                           "event": "restart_loop_halted", "result": "failed",
                           "attempt": restart_attempt,
                           "reason": "max recovery attempts reached; manual intervention required"})
            events.append({"timestamp": _iso(start + timedelta(seconds=cursor + 1)),
                           "event": "recovery_failed", "result": "failed",
                           "detail": "application did not recover automatically"})
            down.append((s0, cursor + MANUAL_FIX_S, kind))

    # Version timeline: v1 -> v2 -> (rollback) v1 -> v3
    v2_off, v3_off = 0.33 * total_s, 0.55 * total_s

    def version_at(off: float) -> str:
        if off >= v3_off:
            return "v3"
        if rollback_done_off is not None and off >= rollback_done_off:
            return "v1"
        if off >= v2_off:
            return "v2"
        return "v1"

    # Health checks every 10 seconds.
    off = 0.0
    while off <= total_s:
        ts = start + timedelta(seconds=off)
        hit = next((d for d in down if d[0] <= off < d[1]), None)
        if hit:
            cs = "exited" if hit[2] == "crash" else "running"
            reason = "connection refused" if hit[2] == "crash" else "timeout"
            events.append(_health_row(ts, False, rng, cs, version_at(off), reason))
        else:
            events.append(_health_row(ts, True, rng, "running", version_at(off)))
        off += CHECK_INTERVAL_S

    events.sort(key=lambda e: e["timestamp"])

    def dep(off_s, version, status, by, detail):
        return {"timestamp": _iso(start + timedelta(seconds=off_s)), "version": version,
                "image": f"autohealops-app:{version}", "status": status,
                "commit": f"{rng.getrandbits(28):07x}", "triggered_by": by, "detail": detail}

    deployments = [
        dep(-3600, "v1", "success", "github-actions", "initial release"),
        dep(v2_off, "v2", "success", "github-actions", "deployed; passed smoke test"),
        dep(0.75 * total_s, "v4", "failed", "github-actions",
            "image build ok, deploy health check failed; kept running version"),
    ]
    if rollback_done_off is not None:
        deployments.append(dep(rollback_done_off, "v2", "rolled_back", "autohealops-monitor",
                               "unrecoverable after 2 restarts"))
        deployments.append(dep(rollback_done_off + 1, "v1", "success", "autohealops-monitor",
                               "automatic rollback to previous stable image"))
    deployments.append(dep(v3_off, "v3", "success", "github-actions", "deployed; passed smoke test"))
    deployments.sort(key=lambda d: d["timestamp"])
    return events, deployments


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps({k: v for k, v in row.items() if v is not None}) + "\n")


def append(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({k: v for k, v in row.items() if v is not None}) + "\n")
        fh.flush()


def run_live(log_path: Path, seed: int) -> None:
    """Append a health check every 10s; occasionally simulate a crash + restart."""
    rng = random.Random(seed)
    print(f"Appending to {log_path} every {CHECK_INTERVAL_S}s. Ctrl+C to stop.")
    while True:
        now = datetime.now(timezone.utc)
        if rng.random() < 0.04:  # simulated crash
            for _ in range(DETECT_AFTER_FAILURES):
                append(log_path, _health_row(datetime.now(timezone.utc), False, rng,
                                             "exited", None, "connection refused"))
                time.sleep(CHECK_INTERVAL_S)
            append(log_path, {"timestamp": _iso(datetime.now(timezone.utc)),
                              "event": "failure_detected", "reason": "container exited unexpectedly",
                              "consecutive_failures": DETECT_AFTER_FAILURES})
            append(log_path, {"timestamp": _iso(datetime.now(timezone.utc)), "event": "restart",
                              "result": "success", "attempt": 1})
            time.sleep(RESTART_COST_S)
            append(log_path, {"timestamp": _iso(datetime.now(timezone.utc)),
                              "event": "recovery_verified", "result": "success",
                              "recovery_time_s": DETECT_AFTER_FAILURES * CHECK_INTERVAL_S + RESTART_COST_S})
        else:
            append(log_path, _health_row(now, True, rng, "running", "v3"))
            time.sleep(CHECK_INTERVAL_S)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hours", type=float, default=6, help="hours of history (min 2)")
    p.add_argument("--out-dir", default=str(Path(__file__).parent / "logs"))
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--live", action="store_true", help="keep appending new events after generating")
    args = p.parse_args()

    out = Path(args.out_dir)
    events, deployments = build_history(max(args.hours, 2), args.seed)
    write_jsonl(out / "recovery_log.jsonl", events)
    write_jsonl(out / "deployments.jsonl", deployments)
    print(f"Wrote {len(events)} events and {len(deployments)} deployments to {out}")
    if args.live:
        run_live(out / "recovery_log.jsonl", args.seed)


if __name__ == "__main__":
    main()
