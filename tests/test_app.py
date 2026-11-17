import sys
from pathlib import Path
import pytest

# Add the main project folder to Python's import path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app as app_module


@pytest.fixture
def client():
    # Reset application state before every test
    app_module.app_status = "healthy"
    app_module.app_unresponsive = False

    app_module.app.config["TESTING"] = True

    with app_module.app.test_client() as client:
        yield client


# Test 1: Home page loads successfully
def test_home_page(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"AutoHealOps" in response.data


# Test 2: Health API returns healthy status
def test_health_healthy(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json["status"] == "healthy"


# Test 3: Unhealthy simulation works
def test_unhealthy_simulation(client):
    response = client.post("/simulate/unhealthy")

    assert response.status_code == 200
    assert response.json["status"] == "unhealthy"


# Test 4: Health API detects unhealthy state
def test_health_unhealthy(client):
    client.post("/simulate/unhealthy")

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json["status"] == "unhealthy"


# Test 5: Healthy restoration works
def test_healthy_restoration(client):
    client.post("/simulate/unhealthy")

    response = client.post("/simulate/healthy")

    assert response.status_code == 200
    assert response.json["status"] == "healthy"


# Test 6: Version identification works
def test_version_identification(client):
    response = client.get("/health")

    assert response.json["version"] == app_module.APP_VERSION


# Test 7: Invalid URL returns 404
def test_invalid_url(client):
    response = client.get("/invalid-page")

    assert response.status_code == 404
    assert response.json["error"] == "Page Not Found"


# Test 8: Internal server error handling
def test_internal_server_error():
    with app_module.app.app_context():
        response, status_code = app_module.internal_server_error(
            Exception("Testing internal error")
        )

        assert status_code == 500
        assert response.get_json()["error"] == "Internal Server Error"


# Test 9: Crash simulation is disabled by default
def test_crash_simulation_disabled(client, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "ALLOW_CRASH_SIMULATION",
        False
    )

    response = client.post("/simulate/crash")

    assert response.status_code == 403
    assert response.json["error"] == "Crash simulation is disabled"


# Test 10: Unresponsive simulation endpoint
def test_unresponsive_simulation(client):
    response = client.post("/simulate/unresponsive")

    assert response.status_code == 200
    assert response.json["status"] == "unresponsive"
    assert app_module.app_unresponsive is True

# Test 11 – Application information
def test_health_response_details(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json["application"] == "AutoHealOps"
    assert response.json["version"] == app_module.APP_VERSION


# Test 12 – Configurable unresponsive delay
def test_unresponsive_delay(client, monkeypatch):
    sleep_calls = []

    monkeypatch.setattr(
        app_module,
        "UNRESPONSIVE_DELAY_SECONDS",
        7
    )

    monkeypatch.setattr(
        app_module.time,
        "sleep",
        lambda seconds: sleep_calls.append(seconds)
    )

    app_module.app_unresponsive = True

    response = client.get("/health")

    assert response.status_code == 200
    assert sleep_calls == [7]

# Test 13 – Restore both failure states
def test_restore_from_failure_states(client):
    client.post("/simulate/unhealthy")
    client.post("/simulate/unresponsive")

    response = client.post("/simulate/healthy")

    assert response.status_code == 200
    assert app_module.app_status == "healthy"
    assert app_module.app_unresponsive is False