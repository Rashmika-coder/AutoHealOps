"""Central configuration for the AutoHealOps dashboard.

Everything can be overridden with environment variables so the same code runs
locally, in Docker Compose and on the EC2 instance.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Directory shared with the monitoring engine (Person 3) and CI/CD (Person 2).
LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))
RECOVERY_LOG = Path(os.getenv("RECOVERY_LOG", LOG_DIR / "recovery_log.jsonl"))
DEPLOY_LOG = Path(os.getenv("DEPLOY_LOG", LOG_DIR / "deployments.jsonl"))

# Live checks against the Flask app (Person 1).
APP_URL = os.getenv("APP_URL", "http://localhost:5000").rstrip("/")
HEALTH_ENDPOINT = os.getenv("HEALTH_ENDPOINT", f"{APP_URL}/health")
HEALTH_TIMEOUT_S = float(os.getenv("HEALTH_TIMEOUT_S", "3"))

# Docker container the monitoring engine is watching.
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "autohealops-app")

# Dashboard behaviour.
DEFAULT_REFRESH_S = int(os.getenv("REFRESH_SECONDS", "10"))
DISPLAY_TZ = os.getenv("DISPLAY_TZ", "UTC")        # e.g. Asia/Kolkata
CHECK_INTERVAL_S = int(os.getenv("CHECK_INTERVAL_S", "10"))  # monitor's polling interval
STALE_AFTER_S = int(os.getenv("STALE_AFTER_S", "60"))        # warn if no check logged for this long

# Event names written by the monitoring engine (see README "Log contract").
EVENT_HEALTH = "health_check"
EVENT_FAILURE = "failure_detected"
EVENT_RESTART = "restart"
EVENT_ROLLBACK = "rollback"
EVENT_VERIFIED = "recovery_verified"
EVENT_RECOVERY_FAILED = "recovery_failed"
EVENT_LOOP_HALT = "restart_loop_halted"

# Column order used when a log file is missing columns.
EVENT_COLUMNS = [
    "timestamp", "event", "status", "result", "http_status", "response_time_ms",
    "container_status", "version", "from_version", "to_version", "attempt",
    "consecutive_failures", "recovery_time_s", "reason", "detail",
]
DEPLOY_COLUMNS = [
    "timestamp", "version", "image", "status", "commit", "triggered_by", "detail",
]
