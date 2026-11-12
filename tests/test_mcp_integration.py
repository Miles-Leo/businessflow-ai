"""Real stdio subprocess and temporary SQLite; no model/Milvus/Feishu calls."""
import asyncio
import os
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import Order, Ticket
from app.db.seed import initialize_demo_data


def server_params(database):
    # Explicit environment overrides .env and prevents access to the project DB.
    return StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_server"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}"},
    )


def test_stdio_discovery_query_validation_and_read_only(tmp_path):
    database = tmp_path / "orders.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    initialize_demo_data(engine)

    async def scenario():
        async with Client(server_params(database), read_timeout_seconds=20) as client:
            listing = await client.list_tools()
            assert [tool.name for tool in listing.tools] == ["lookup_order"]
            schema = listing.tools[0].input_schema
            assert "order_id" in schema["properties"]

            found = await client.call_tool("lookup_order", {"order_id": "BF2026001"})
            assert not found.is_error
            assert found.structured_content["status"] == "success"
            assert found.structured_content["data"]["order_id"] == "BF2026001"
            assert found.structured_content["data"]["status"] == "pending"

            missing = await client.call_tool("lookup_order", {"order_id": "BF9999999"})
            assert not missing.is_error
            assert missing.structured_content["status"] == "not_found"
            assert missing.structured_content["data"] is None

            invalid = await client.call_tool("lookup_order", {"order_id": "123"})
            assert invalid.is_error
            assert invalid.structured_content is None

    try:
        asyncio.run(asyncio.wait_for(scenario(), timeout=60))
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Order)) == 3
            assert session.get(Order, "BF2026001").status == "pending"
            assert session.scalar(select(func.count()).select_from(Ticket)) == 0
    finally:
        engine.dispose()


def test_stdio_database_failure_is_business_failed(tmp_path):
    # Deliberately uninitialized temporary DB: valid input, SQL query fails.
    database = tmp_path / "uninitialized.db"

    async def scenario():
        async with Client(server_params(database), read_timeout_seconds=20) as client:
            result = await client.call_tool("lookup_order", {"order_id": "BF2026001"})
            assert not result.is_error
            assert result.structured_content == {
                "status": "failed", "data": None,
                "error": "订单查询暂时不可用，请稍后重试",
            }

    asyncio.run(asyncio.wait_for(scenario(), timeout=60))
