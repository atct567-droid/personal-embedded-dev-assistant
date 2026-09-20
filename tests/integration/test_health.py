from pathlib import Path

import httpx
import pytest

from app.api import app
from app.config import Settings
from app.runtime import ApplicationRuntime, get_runtime


@pytest.mark.anyio
async def test_health_has_trace_and_offline_mode(tmp_path: Path) -> None:
    previous = getattr(app.state, "runtime", None)
    app.state.runtime = ApplicationRuntime.from_settings(Settings.from_root(tmp_path))
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["mode"] == "offline-mock"
        assert response.headers["X-Trace-ID"] == body["trace_id"]
    finally:
        if previous is None:
            del app.state.runtime
        else:
            app.state.runtime = previous


@pytest.mark.anyio
async def test_http_errors_are_stable_and_have_trace() -> None:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/does-not-exist")
        method = await client.post("/health")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert missing.headers["X-Trace-ID"] == missing.json()["trace_id"]
    assert method.status_code == 405
    assert method.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.anyio
async def test_health_is_degraded_for_incomplete_remote_config(monkeypatch) -> None:
    previous = getattr(app.state, "runtime", None)
    if previous is not None:
        del app.state.runtime
    get_runtime.cache_clear()
    monkeypatch.setenv("PDA_LLM_PROVIDER", "openai-compatible")
    monkeypatch.delenv("PDA_ALLOW_REMOTE_MODELS", raising=False)
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
    finally:
        get_runtime.cache_clear()
        if previous is not None:
            app.state.runtime = previous
