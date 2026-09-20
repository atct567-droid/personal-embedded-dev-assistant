from pathlib import Path

import httpx
import pytest

from app.api import app
from app.config import Settings
from app.runtime import ApplicationRuntime


@pytest.mark.anyio
async def test_agent_api_run_session_and_confirm(tmp_path: Path) -> None:
    settings = Settings.from_root(tmp_path)
    settings.ensure_directories()
    source = settings.inbox_dir / "uart.md"
    source.write_text("# UART\nPA9 作为 TX。", encoding="utf-8")
    (settings.logs_dir / "device.log").write_text("ERROR uart timeout\n", encoding="utf-8")
    runtime = ApplicationRuntime.from_settings(settings)
    runtime.indexer.ingest_file(source, relative_path="uart.md")
    previous = getattr(app.state, "runtime", None)
    app.state.runtime = runtime
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/agent/run", json={"user_goal": "检查 PA9 UART timeout"}
            )
            state = response.json()
            session = await client.get(f"/v1/sessions/{state['session_id']}")
            confirmed = await client.post(
                "/v1/agent/confirm",
                json={"session_id": state["session_id"], "confirm": False},
            )
        assert response.status_code == 200
        assert state["pending_confirmation"] is True
        assert session.status_code == 200
        assert confirmed.status_code == 200
        assert confirmed.json()["pending_confirmation"] is False
        assert response.headers["X-Trace-ID"] == state["trace_id"]
    finally:
        if previous is None:
            del app.state.runtime
        else:
            app.state.runtime = previous
