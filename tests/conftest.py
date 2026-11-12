import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.seed import initialize_demo_data
from app.db.session import get_db
from app.main import app


@pytest.fixture
def db_engine(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", connect_args={"check_same_thread": False})
    initialize_demo_data(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(db_engine):
    def override_db():
        with Session(db_engine) as session:
            yield session
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
