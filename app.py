import os
from flask import Flask, jsonify, render_template
import time

app = Flask(
    __name__,
    template_folder="app/templates",
    static_folder="app/static"
)

APP_NAME = "AutoHealOps"
APP_VERSION = os.getenv("APP_VERSION", "1.0")

ALLOW_CRASH_SIMULATION = (
    os.getenv("ALLOW_CRASH_SIMULATION", "false").lower() == "true"
)

UNRESPONSIVE_DELAY_SECONDS = int(
    os.getenv("UNRESPONSIVE_DELAY_SECONDS", "30")
)

app_status = "healthy"
app_unresponsive = False


@app.route("/")
def home():
    return render_template(
        "index.html",
        status=app_status.upper(),
        version=APP_VERSION
    )


@app.route("/health")
def health():

    # Simulate an application that is not responding
    if app_unresponsive:
        time.sleep(UNRESPONSIVE_DELAY_SECONDS)

    response = {
        "application": APP_NAME,
        "status": app_status,
        "version": APP_VERSION
    }

    if app_status == "healthy":
        return jsonify(response), 200

    return jsonify(response), 503


@app.route("/simulate/unhealthy", methods=["POST"])
def simulate_unhealthy():
    global app_status, app_unresponsive

    app_status = "unhealthy"
    app_unresponsive = False

    return jsonify({
        "message": "Failure simulated successfully",
        "status": app_status
    })


@app.route("/simulate/unresponsive", methods=["POST"])
def simulate_unresponsive():
    global app_unresponsive

    app_unresponsive = True

    return jsonify({
        "message": "Application is now simulating an unresponsive state",
        "status": "unresponsive"
    })


@app.route("/simulate/healthy", methods=["POST"])
def simulate_healthy():
    global app_status, app_unresponsive

    app_status = "healthy"
    app_unresponsive = False

    return jsonify({
        "message": "Application restored successfully",
        "status": app_status
    })


@app.route("/simulate/crash", methods=["POST"])
def simulate_crash():

    if not ALLOW_CRASH_SIMULATION:
        return jsonify({
            "error": "Crash simulation is disabled"
        }), 403

    print("CRITICAL: Simulating application crash!")

    # Immediately terminate the Flask process
    os._exit(1)


# Handle invalid URLs (404)
@app.errorhandler(404)
def page_not_found(error):
    return jsonify({
        "error": "Page Not Found",
        "message": "The requested URL does not exist."
    }), 404


# Handle internal server errors (500)
@app.errorhandler(500)
def internal_server_error(error):
    return jsonify({
        "error": "Internal Server Error",
        "message": "Something went wrong in the application."
    }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True,
        use_reloader=False
    )
