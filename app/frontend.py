# 模块职责：可选托管 Vue 构建产物；不替代业务 API 或在启动时执行构建。
"""Serve an optional compiled Vue workbench without changing API routes."""
from pathlib import Path

from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles


def configure_frontend(application, dist: Path | None = None):
    directory = dist if dist is not None else Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if directory.is_dir() and (directory / "index.html").is_file():
        application.mount("/app", StaticFiles(directory=directory, html=True), name="workbench")
        target = "/app/"
    else:
        target = "/docs"

    @application.get("/", include_in_schema=False)
    def landing():
        return RedirectResponse(target)
