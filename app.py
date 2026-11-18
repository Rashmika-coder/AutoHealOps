
import os
import time

from flask import Flask, jsonify, render_template
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST

app = Flask(
    __name__,
    template_folder="app/templates",
    static_folder="app/static"
)

# --------------------------------------------------
# Application Configuration
# --------------------------------------------------

APP_NAME = "AutoHealOps"
APP_VERSION = os.getenv("APP_VERSION", "1.0")

ALLOW_CRASH_SIMULATION = (
    os.getenv("ALLOW_CRASH_SIMULATION", "false").lower() == "true"
)

UNRESPONSIVE_DELAY_SECONDS = int(
    os.getenv("UNRESPONSIVE_DELAY_SECONDS", "30")
)

# Application state
app_status = "healthy"
app_unresponsive = False


# --------------------------------------------------
# Prometheus Metrics
# --------------------------------------------------

health_checks_total = Counter(
    "autohealops_health_checks_total",
    "Total application health checks",
    ["result"]
)

health_status_metric = Gauge(
    "autohealops_health_status",
    "Application health status (1 healthy, 0 unhealthy)"
)

# Initialize the application health metric
health_status_metric.set(1)


# --------------------------------------------------
# Home Route
# --------------------------------------------------

@app.route("/")
def home():
    return render_template(
        "index.html",
        status=app_status.upper(),
        version=APP_VERSION
    )


# --------------------------------------------------
# Health Check Route
# --------------------------------------------------

@app.route("/health")
def health():

    # Simulate an unresponsive application
    if app_unresponsive:
        time.sleep(UNRESPONSIVE_DELAY_SECONDS)

    response = {
        "application": APP_NAME,
        "status": app_status,
        "version": APP_VERSION
    }

    if app_status == "healthy":
        health_checks_total.labels(result="healthy").inc()
        health_status_metric.set(1)

        return jsonify(response), 200

    health_checks_total.labels(result="unhealthy").inc()
    health_status_metric.set(0)

    return jsonify(response), 503


# --------------------------------------------------
# Failure Simulation: Unhealthy
# --------------------------------------------------

@app.route("/simulate/unhealthy", methods=["POST"])
def simulate_unhealthy():
    global app_status, app_unresponsive

    app_status = "unhealthy"
    app_unresponsive = False

    health_status_metric.set(0)

    return jsonify({
        "message": "Failure simulated successfully",
        "status": app_status
    }), 200


# --------------------------------------------------
# Failure Simulation: Unresponsive
# --------------------------------------------------

@app.route("/simulate/unresponsive", methods=["POST"])
def simulate_unresponsive():
    global app_unresponsive

    app_unresponsive = True

    return jsonify({
        "message": "Application is now simulating an unresponsive state",
        "status": "unresponsive"
    }), 200


# --------------------------------------------------
# Recovery Simulation: Healthy
# --------------------------------------------------

@app.route("/simulate/healthy", methods=["POST"])
def simulate_healthy():
    global app_status, app_unresponsive

    app_status = "healthy"
    app_unresponsive = False

    health_status_metric.set(1)

    return jsonify({
        "message": "Application restored successfully",
        "status": app_status
    }), 200


# --------------------------------------------------
# Failure Simulation: Crash
# --------------------------------------------------

@app.route("/simulate/crash", methods=["POST"])
def simulate_crash():

    if not ALLOW_CRASH_SIMULATION:
        return jsonify({
            "error": "Crash simulation is disabled"
        }), 403

    print("CRITICAL: Simulating application crash!")

    # Immediately terminate the Flask process
    os._exit(1)


# --------------------------------------------------
# Prometheus Metrics Endpoint
# --------------------------------------------------

@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {
        "Content-Type": CONTENT_TYPE_LATEST
    }


# --------------------------------------------------
# Error Handlers
# --------------------------------------------------

@app.errorhandler(404)
def page_not_found(error):
    return jsonify({
        "error": "Page Not Found",
        "message": "The requested URL does not exist."
    }), 404


@app.errorhandler(500)
def internal_server_error(error):
    return jsonify({
        "error": "Internal Server Error",
        "message": "Something went wrong in the application."
    }), 500


# --------------------------------------------------
# Application Entry Point
# --------------------------------------------------

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True,
        use_reloader=False
    )
