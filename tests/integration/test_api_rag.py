from pathlib import Path

import httpx
import pytest

from app.api import app
from app.config import Settings
from app.runtime import ApplicationRuntime


@pytest.mark.anyio
async def test_ingest_scan_query_incremental_and_trace(tmp_path: Path) -> None:
    settings = Settings.from_root(tmp_path)
    settings.ensure_directories()
    source = settings.inbox_dir / "uart.md"
    source.write_text("# UART\nPA9 作为 TX，PA10 作为 RX。", encoding="utf-8")
    runtime = ApplicationRuntime.from_settings(settings)
    previous = getattr(app.state, "runtime", None)
    app.state.runtime = runtime
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post("/v1/documents/ingest", json={"source_path": "uart.md"})
            second = await client.post("/v1/documents/ingest", json={"source_path": "uart.md"})
            scan = await client.post("/v1/documents/scan", json={})
            query = await client.post("/v1/rag/query", json={"question": "PA9 是什么？"})
            trace = await client.get(f"/v1/traces/{query.json()['trace_id']}")
        assert first.status_code == 200 and first.json()["status"] == "indexed"
        assert second.json()["status"] == "unchanged"
        assert scan.status_code == 200 and scan.json()["unchanged"] == 1
        assert query.status_code == 200 and query.json()["citations"]
        assert query.json()["session_id"]
        assert len(trace.json()["events"]) >= 2
        assert query.headers["X-Trace-ID"] == query.json()["trace_id"]
    finally:
        if previous is None:
            del app.state.runtime
        else:
            app.state.runtime = previous


@pytest.mark.anyio
async def test_ingest_rejects_path_traversal(tmp_path: Path) -> None:
    runtime = ApplicationRuntime.from_settings(Settings.from_root(tmp_path))
    previous = getattr(app.state, "runtime", None)
    app.state.runtime = runtime
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/documents/ingest", json={"source_path": "..\\outside.txt"}
            )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "PATH_NOT_ALLOWED"
    finally:
        if previous is None:
            del app.state.runtime
        else:
            app.state.runtime = previous
