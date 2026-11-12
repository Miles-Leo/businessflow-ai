from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.main import app
from app.core.config import Settings

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "businessflow-ai"}

def test_order(client):
    response = client.get("/api/v1/orders/BF2026001", headers={"X-Demo-User": "employee-demo-001"})
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == "BF2026001"
    assert data["customer_id"] == "CUST-DEMO-001"
    assert data["shipped_at"] is None
    assert data["promised_ship_at"].endswith("+08:00")

def test_missing_order(client):
    assert client.get("/api/v1/orders/missing", headers={"X-Demo-User": "employee-demo-001"}).status_code == 404

def test_docs():
    assert client.get("/docs").status_code == 200
    assert "/api/v1/orders/{order_id}" in client.get("/openapi.json").json()["paths"]

def test_config(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Test App")
    assert Settings(_env_file=None).app_name == "Test App"

def test_database():
    from app.db.session import Base, get_db
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as session:
        assert session.scalar(text("SELECT 1")) == 1
    engine.dispose()
