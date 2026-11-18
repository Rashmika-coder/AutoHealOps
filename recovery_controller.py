
import logging
import os
import time

import docker
from docker.errors import DockerException
from prometheus_client import Counter, start_http_server

# --------------------------------------------------
# Configuration
# --------------------------------------------------

TARGET_CONTAINER = os.getenv(
    "TARGET_CONTAINER",
    "autohealops-app"
)

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))
FAILURE_THRESHOLD = int(os.getenv("FAILURE_THRESHOLD", "2"))
RESTART_COOLDOWN = int(os.getenv("RESTART_COOLDOWN", "60"))
RECOVERY_TIMEOUT = int(os.getenv("RECOVERY_TIMEOUT", "60"))

# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger("AutoHealOps-Recovery")

# --------------------------------------------------
# Prometheus Metrics
# --------------------------------------------------

recovery_events_total = Counter(
    "autohealops_recovery_events_total",
    "Total automatic recovery actions performed"
)

recovery_success_total = Counter(
    "autohealops_recovery_success_total",
    "Total successful automatic recoveries"
)

recovery_failure_total = Counter(
    "autohealops_recovery_failure_total",
    "Total failed automatic recoveries"
)

# --------------------------------------------------
# Docker Client
# --------------------------------------------------

client = docker.from_env()

# --------------------------------------------------
# Recovery Verification
# --------------------------------------------------

def wait_for_recovery(container):
    """Wait for the container to become healthy after restart."""

    start_time = time.time()

    while time.time() - start_time < RECOVERY_TIMEOUT:
        try:
            container.reload()

            health = (
                container.attrs.get("State", {})
                .get("Health", {})
                .get("Status", "unknown")
            )

            logger.info(
                "Recovery verification: container=%s health=%s",
                container.name,
                health
            )

            if health == "healthy":
                logger.info(
                    "RECOVERY SUCCESS: %s is healthy again",
                    container.name
                )
                return True

            time.sleep(CHECK_INTERVAL)

        except DockerException as error:
            logger.error("Recovery verification error: %s", error)
            time.sleep(CHECK_INTERVAL)

    logger.error(
        "RECOVERY FAILED: %s did not become healthy within %s seconds",
        container.name,
        RECOVERY_TIMEOUT
    )

    return False

# --------------------------------------------------
# Recovery Controller
# --------------------------------------------------

def main():

    # Start Prometheus metrics server
    start_http_server(8001)

    logger.info("AutoHealOps Recovery Controller started")
    logger.info("Monitoring container: %s", TARGET_CONTAINER)
    logger.info("Prometheus metrics available on port 8001")

    consecutive_failures = 0
    last_restart_time = 0

    while True:
        try:
            container = client.containers.get(TARGET_CONTAINER)
            container.reload()

            state = container.attrs.get("State", {})
            status = state.get("Status", "unknown")

            health = (
                state.get("Health", {}).get("Status", "no-healthcheck")
            )

            logger.info(
                "Monitoring: container=%s status=%s health=%s",
                TARGET_CONTAINER,
                status,
                health
            )

            # Container has stopped
            if status != "running":
                logger.warning(
                    "Container is not running: %s",
                    status
                )
                consecutive_failures += 1

            # Docker healthcheck detects unhealthy state
            elif health == "unhealthy":
                consecutive_failures += 1

                logger.warning(
                    "Unhealthy detection: failure count=%s/%s",
                    consecutive_failures,
                    FAILURE_THRESHOLD
                )

            elif health == "healthy":
                consecutive_failures = 0

            else:
                consecutive_failures = 0

            # Trigger recovery
            if consecutive_failures >= FAILURE_THRESHOLD:

                current_time = time.time()

                if (
                    current_time - last_restart_time
                    < RESTART_COOLDOWN
                ):
                    logger.warning(
                        "Restart cooldown active. Skipping restart."
                    )

                    consecutive_failures = 0
                    time.sleep(CHECK_INTERVAL)
                    continue

                logger.critical(
                    "RECOVERY ACTION: restarting container %s",
                    TARGET_CONTAINER
                )

                last_restart_time = current_time

                # Count recovery attempt
                recovery_events_total.inc()

                try:
                    container.restart(timeout=10)

                    logger.info(
                        "Restart command executed for %s",
                        TARGET_CONTAINER
                    )

                    consecutive_failures = 0

                    # Verify recovery
                    if wait_for_recovery(container):
                        recovery_success_total.inc()
                    else:
                        recovery_failure_total.inc()

                except DockerException as error:
                    recovery_failure_total.inc()

                    logger.exception(
                        "Restart failed: %s",
                        error
                    )

            time.sleep(CHECK_INTERVAL)

        except docker.errors.NotFound:
            logger.error(
                "Target container not found: %s",
                TARGET_CONTAINER
            )
            time.sleep(CHECK_INTERVAL)

        except DockerException as error:
            logger.error(
                "Docker connection error: %s",
                error
            )
            time.sleep(CHECK_INTERVAL)

        except Exception:
            logger.exception("Unexpected controller error")
            time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
