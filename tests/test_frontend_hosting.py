from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend import configure_frontend


def test_compiled_workbench_and_assets_are_served_without_hiding_api(tmp_path):
    (tmp_path / "index.html").write_text('<html lang="zh-CN"><title>BusinessFlow AI</title></html>', encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text('console.log("test")', encoding="utf-8")
    app = FastAPI()

    @app.get("/api/v1/test")
    def api():
        return {"ok": True}

    configure_frontend(app, tmp_path)
    with TestClient(app) as client:
        assert client.get("/").url.path == "/app/"
        assert "BusinessFlow AI" in client.get("/app/").text
        assert client.get("/app/assets/app.js").status_code == 200
        assert client.get("/api/v1/test").json() == {"ok": True}
        assert client.get("/docs").status_code == 200


def test_api_only_mode_still_starts_without_frontend_build(tmp_path):
    app = FastAPI()
    configure_frontend(app, tmp_path / "not-built")
    with TestClient(app) as client:
        assert client.get("/").url.path == "/docs"
        assert client.get("/app/").status_code == 404
