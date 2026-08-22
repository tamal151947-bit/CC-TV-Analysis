from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_home_page_loads():
    response = client.get("/")
    assert response.status_code == 200


def test_login_page_loads():
    response = client.get("/login")
    assert response.status_code == 200


def test_admin_login_success():
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers.get("set-cookie") is not None


def test_cameras_endpoint():
    response = client.get("/api/cameras")
    assert response.status_code == 200
    assert "cameras" in response.json()


def test_connect_camera_endpoint():
    response = client.post(
        "/api/cameras/connect",
        json={
            "name": "Test entrance",
            "location": "Main gate",
            "rtsp_url": "rtsp://user:password@192.168.1.50:554/stream1",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "connected"


def test_alert_endpoint():
    response = client.post("/api/test-alert")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_simulate_activity_endpoint():
    camera_id = "cam-01"
    response = client.post(
        f"/api/cameras/{camera_id}/simulate-activity",
        json={"threat_type": "theft", "confidence": 0.92},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "alert_created"
