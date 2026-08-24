from fastapi.testclient import TestClient

from app.main import app
from app.subscription_service import get_plan_for_camera_count, process_subscription_payment

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


def test_remove_camera_endpoint():
    client.post("/login", data={"username": "admin", "password": "admin123"})
    response = client.post(
        "/api/cameras/connect",
        json={
            "name": "Removable camera",
            "location": "Test room",
            "rtsp_url": "webcam://0",
            "connection_type": "webcam",
        },
    )
    camera_id = response.json()["camera"]["id"]

    response = client.request("DELETE", f"/api/cameras/{camera_id}", json={"password": "admin123"})

    assert response.status_code == 200
    assert response.json() == {"status": "removed", "camera_id": camera_id}
    assert client.request("DELETE", f"/api/cameras/{camera_id}", json={"password": "admin123"}).status_code == 404


def test_alert_endpoint():
    response = client.post("/api/test-alert")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_simulate_activity_endpoint():
    response = client.post(
        "/api/cameras/connect",
        json={
            "name": "Simulation camera",
            "location": "Test zone",
            "rtsp_url": "rtsp://camera.example/1",
        },
    )
    camera_id = response.json()["camera"]["id"]
    response = client.post(
        f"/api/cameras/{camera_id}/simulate-activity",
        json={"threat_type": "theft", "confidence": 0.92},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "alert_created"


def test_plan_pricing_and_validity():
    free_plan = get_plan_for_camera_count(2)
    starter_plan = get_plan_for_camera_count(3)
    pro_plan = get_plan_for_camera_count(8)
    enterprise_plan = get_plan_for_camera_count(12)

    assert free_plan["code"] == "free"
    assert starter_plan["price_inr"] == 1
    assert pro_plan["price_inr"] == 299
    assert enterprise_plan["price_inr"] == 499

    payment = process_subscription_payment("demo-user", "pro", auto_renew=True, payment_method="UPI")
    assert payment["status"] == "paid"
    assert payment["expires_in_days"] == 30
    assert payment["auto_renew"] is True
