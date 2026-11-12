from datetime import datetime, timezone
import os
import subprocess
import sys
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.db.models import Customer, Order
from app.db.seed import initialize_demo_data


def test_seed_preserves_existing_data(db_engine):
    with Session(db_engine) as session, session.begin():
        session.get(Customer, "CUST-DEMO-001").name = "Edited customer"
        session.get(Order, "BF2026001").status = "edited"
    initialize_demo_data(db_engine)
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(Order)) == 3
        assert session.scalar(select(func.count()).select_from(Customer)) == 1
        assert session.get(Customer, "CUST-DEMO-001").name == "Edited customer"
        assert session.get(Order, "BF2026001").status == "edited"


def test_shipping_scenarios(client):
    def order(number):
        response = client.get(f"/api/v1/orders/{number}", headers={"X-Demo-User": "employee-demo-001"})
        assert response.status_code == 200
        return response.json()
    def dt(value):
        return datetime.fromisoformat(value)
    pending = order("BF2026001")
    normal = order("BF2026002")
    late = order("BF2026003")
    assert pending["shipped_at"] is None
    assert dt(pending["promised_ship_at"]) < datetime(2026, 11, 4, tzinfo=timezone.utc)
    assert dt(normal["shipped_at"]) <= dt(normal["promised_ship_at"])
    assert dt(late["shipped_at"]) > dt(late["promised_ship_at"])


def test_startup_does_not_create_database(tmp_path):
    db = tmp_path / "uninitialized.db"
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db.as_posix()}")
    subprocess.run([sys.executable, "-c", "from fastapi.testclient import TestClient; from app.main import app; client = TestClient(app); assert client.get('/health').status_code == 200"], env=env, check=True, capture_output=True)
    assert not db.exists()
