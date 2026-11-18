# AutoHealOps – Streamlit Dashboard (Person 4)

Dashboard, logging integration and analytics for the AutoHealOps self-healing system.
It reads the logs written by the monitoring engine and CI/CD pipeline, probes the app's
`/health` endpoint and the Docker container live, and refreshes automatically.

## Deliverables checklist

| Requirement | Where |
|---|---|
| Streamlit dashboard, layout and navigation | `app.py` (sidebar navigation, 6 pages) |
| Application health status | Overview page (live `/health` probe + logged uptime) |
| Docker container status | Container status page (live `docker inspect` + history from logs) |
| Deployment history | Deployment history page (reads `deployments.jsonl`) |
| Detected failures | Failures page |
| Restart and rollback history | Recovery history page |
| Recovery success / failure statistics | Overview KPIs + Recovery history page |
| Charts: uptime and failure frequency | Overview, Failures and Analytics pages |
| Integration with monitoring logs | `data_loader.py` (JSON Lines, tolerant of partial lines) |
| Automatic refresh | Sidebar toggle + interval (5–60 s, default 10 s) |
| Unit tests | `tests/` (39 tests, including headless render of every page) |

## Quick start

```bash
pip install -r requirements-dev.txt
python generate_sample_data.py          # demo logs, so you can work before the others finish
streamlit run app.py                    # http://localhost:8501
```

To watch the auto-refresh and the "monitor stopped" warning behave, in a second terminal run:

```bash
python generate_sample_data.py --live   # appends a health check every 10 s, with occasional crashes
```

Run the tests: `python -m pytest -q`

## Log contract (what Persons 1–3 must produce)

The dashboard reads two **JSON Lines** files (one JSON object per line, appended to). Both
must contain an ISO-8601 `timestamp` (UTC, e.g. `2026-11-16T10:00:00Z`). Unknown extra
fields are ignored; missing optional fields are fine.

### `logs/recovery_log.jsonl` – written by the monitoring engine (Person 3)

| `event` | Meaning | Fields used |
|---|---|---|
| `health_check` | One poll (every 10 s) | `status` (`healthy`/`unhealthy`), `http_status`, `response_time_ms`, `container_status` (`running`/`exited`/`restarting`…), `version`, `reason` |
| `failure_detected` | Repeated failures confirmed | `reason`, `consecutive_failures`, `container_status` |
| `restart` | Container restart attempted | `result` (`success`/`failed`), `attempt`, `detail` |
| `rollback` | Rollback to previous stable image | `result` (`success`/`failed`), `from_version`, `to_version`, `detail` |
| `recovery_verified` | App healthy again after recovery | `result` = `success`, `recovery_time_s` (seconds from first failed check) |
| `recovery_failed` | App did not recover | `result` = `failed`, `detail` |
| `restart_loop_halted` | Max attempts reached, engine stops retrying | `attempt`, `reason` |

Example lines:

```json
{"timestamp": "2026-11-16T10:00:00Z", "event": "health_check", "status": "healthy", "http_status": 200, "response_time_ms": 18.4, "container_status": "running", "version": "v2"}
{"timestamp": "2026-11-16T10:00:30Z", "event": "failure_detected", "reason": "health check timeout", "consecutive_failures": 3}
{"timestamp": "2026-11-16T10:00:33Z", "event": "restart", "result": "failed", "attempt": 1}
{"timestamp": "2026-11-16T10:00:58Z", "event": "rollback", "result": "success", "from_version": "v2", "to_version": "v1"}
{"timestamp": "2026-11-16T10:01:10Z", "event": "recovery_verified", "result": "success", "recovery_time_s": 40.0}
```

Dashboard metrics are derived like this:

* **Uptime %** = healthy `health_check` rows ÷ all `health_check` rows
* **Recovery success rate** = `recovery_verified` ÷ (`recovery_verified` + `recovery_failed` + `restart_loop_halted`)
* **MTTR** = mean `recovery_time_s` of `recovery_verified` events

> Python snippet for Person 3: `with open(path, "a") as f: f.write(json.dumps(event) + "\n")`
> (use `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"` for the timestamp).

### `logs/deployments.jsonl` – written by CI/CD (Person 2)

One line per deployment, appended by the deploy step on EC2 (and by the monitor after a rollback):

```json
{"timestamp": "2026-11-16T09:30:00Z", "version": "v2", "image": "autohealops-app:v2", "status": "success", "commit": "ad6a07e", "triggered_by": "github-actions", "detail": "deployed; passed smoke test"}
```

`status` is `success`, `failed` or `rolled_back`.

### Needed from Person 1

`GET /health` should return HTTP 200 for healthy, and JSON such as
`{"status": "healthy", "version": "v2"}`. Any non-200 or timeout shows as unhealthy/unreachable.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `LOG_DIR` | `./logs` | Folder holding both log files |
| `RECOVERY_LOG`, `DEPLOY_LOG` | inside `LOG_DIR` | Override individual file paths |
| `APP_URL` | `http://localhost:5000` | Flask app base URL |
| `HEALTH_ENDPOINT` | `$APP_URL/health` | Full health URL |
| `CONTAINER_NAME` | `autohealops-app` | Container to inspect |
| `REFRESH_SECONDS` | `10` | Default auto-refresh interval |
| `DISPLAY_TZ` | `UTC` | Default display timezone (`Asia/Kolkata`, …) |
| `STALE_AFTER_S` | `60` | Warn if no health check logged for this long |

## Docker / EC2

```bash
docker build -t autohealops-dashboard .
docker compose -f docker-compose.dashboard.yml up -d
```

Hand `docker-compose.dashboard.yml` to Person 2 to merge into the main compose file. Requirements:

1. The dashboard and monitoring engine share the same `./logs` folder (volume).
2. `/var/run/docker.sock` is mounted so live container status works (without it, the
   dashboard falls back to the container status recorded in the logs).
3. Open port **8501** in the EC2 security group.

## Project structure

```
app.py                       Streamlit UI (pages, charts, auto-refresh)
analytics.py                 Uptime, failure frequency, recovery stats (pure pandas)
data_loader.py               Log reader, live /health probe, docker inspect
config.py                    Paths, event names, env-var settings
generate_sample_data.py      Demo logs (history and --live mode)
tests/                       Unit tests and headless page-render tests
Dockerfile, docker-compose.dashboard.yml
```

## Troubleshooting

* **"No … yet" messages** – the log files are empty or missing; run `generate_sample_data.py`.
* **"No health check has been logged for …"** – the monitoring engine isn't writing; check its container and that it shares `LOG_DIR`.
* **Container shows "Live Docker status unavailable"** – the Docker CLI or socket isn't reachable from the dashboard host/container.
* **"N unreadable log lines were skipped"** – a line isn't valid JSON (a half-written line is harmless and disappears on the next refresh).
