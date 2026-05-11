# Admin Frontend P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P0 admin-frontend workspace (skeleton + Overview page + Conversation Console page) per `docs/superpowers/specs/2026-05-11-admin-frontend-p0-design.md`, and add the three backend GETs that feed Overview.

**Architecture:** Independent React+TS+Vite+Tailwind+shadcn workspace at `admin-frontend/`. Talks to OLV via existing `/client-ws` (no protocol changes) and three new GET endpoints (`/api/health`, `/api/runtime/snapshot`, `/api/runtime/recent-errors`). Production deploys via `StaticFiles` mount at `/admin` on the OLV FastAPI server. Sensitive config values are server-side-masked.

**Tech Stack:** React 18, TypeScript strict, Vite 5, Tailwind 3, shadcn/ui, TanStack Query v5, Zustand 4, react-router-dom v6, i18next, pixi.js 7 + pixi-live2d-display, Web Audio API, vitest + @testing-library/react. Backend additions use existing FastAPI + loguru; tests use pytest + httpx (added as dev dependencies).

---

## File Structure

**Backend (new/modified):**
- Create: `src/open_llm_vtuber/recent_errors.py` — singleton ring-buffer + loguru sink installer
- Create: `src/open_llm_vtuber/admin_routes.py` — three GETs and Pydantic models
- Modify: `src/open_llm_vtuber/server.py` — install sink, include router, mount `/admin`
- Modify: `pyproject.toml` — add `[dependency-groups] dev = [pytest, pytest-asyncio, httpx]`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_recent_errors.py`
- Create: `tests/test_admin_routes.py`

**Frontend workspace `admin-frontend/`:**
- `package.json`, `tsconfig.json`, `tsconfig.node.json`, `vite.config.ts`, `tailwind.config.ts`, `postcss.config.js`, `components.json`, `index.html`, `.eslintrc.cjs`, `.prettierrc`, `vitest.config.ts`, `README.md`
- `src/main.tsx`, `src/App.tsx`, `src/routes.tsx`, `src/i18n.ts`, `src/index.css`
- `src/lib/{api-client,ws-client,ws-protocol,mask,utils}.ts`
- `src/stores/{connection-store,session-store,settings-store}.ts`
- `src/hooks/{use-health,use-runtime-snapshot,use-recent-errors}.ts`
- `src/components/ui/*` (shadcn generated)
- `src/components/shell/{AppShell,TopBar,SideNav}.tsx`
- `src/components/status/{StatusBadge,HealthCard,GlobalHealthBadge}.tsx`
- `src/components/conversation/{HistoryPanel,ConversationPanel,MessageList,MessageBubble,Composer,BroadcastStateBadge,ProcessDrawer}.tsx`
- `src/components/avatar/{StagePanel,Live2DStage}.tsx`, `src/components/avatar/audio-queue-controller.ts`
- `src/pages/{OverviewPage,ConversationPage,NotFoundPage}.tsx`
- `src/locales/{zh-CN,en-US}/{common,overview,conversation}.json`
- `src/__tests__/*` mirrors source paths

**Docs:**
- Create: `docs/admin-frontend.md`

---

## Conventions

- **Commits:** every task ends with a commit. Use Conventional Commits: `feat(admin): …`, `feat(admin-frontend): …`, `test(admin): …`, `chore(admin-frontend): …`, `docs(admin): …`.
- **Frontend tests:** strict TDD only for pure logic modules (`audio-queue-controller`, `ws-client`, `mask`, `GlobalHealthBadge` derivation). UI components get smoke render tests written after the component when noted explicitly.
- **Backend tests:** strict TDD — write the failing test first.
- **No formatting noise:** run `ruff format .` after backend changes and `npm run format` after frontend changes before committing.

---

## Task 1: Add backend dev dependencies and tests scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add dev dependency group to `pyproject.toml`**

Append (or merge into existing `[dependency-groups]` if present):

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.28.1",
]
```

- [ ] **Step 2: Install dev deps**

Run: `uv sync --group dev`
Expected: exit 0; pytest available via `uv run pytest --version`.

- [ ] **Step 3: Create `tests/__init__.py`**

Empty file.

- [ ] **Step 4: Create `tests/conftest.py`**

```python
import pytest


@pytest.fixture(autouse=True)
def _reset_loguru():
    """Avoid loguru sinks leaking between tests."""
    from loguru import logger

    yield
    # Remove every sink added by tests; restore default sink.
    logger.remove()
    logger.add(lambda msg: None, level="WARNING")
```

- [ ] **Step 5: Sanity check**

Run: `uv run pytest tests -q`
Expected: `no tests ran` (or 0 collected) — succeeds.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tests/__init__.py tests/conftest.py
git commit -m "chore: add pytest dev deps and tests scaffolding"
```

---

## Task 2: Recent-errors ring buffer (TDD)

**Files:**
- Create: `tests/test_recent_errors.py`
- Create: `src/open_llm_vtuber/recent_errors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_recent_errors.py
from loguru import logger

from src.open_llm_vtuber.recent_errors import (
    RecentErrorsBuffer,
    install_loguru_sink,
    get_buffer,
)


def test_buffer_records_warning_and_error(tmp_path):
    buf = RecentErrorsBuffer(maxlen=10)
    sink_id = install_loguru_sink(buf)
    try:
        logger.info("ignored info")
        logger.warning("first warn")
        logger.error("boom")
    finally:
        logger.remove(sink_id)

    items = buf.snapshot()
    assert len(items) == 2
    levels = [it["level"] for it in items]
    assert levels == ["WARNING", "ERROR"]
    assert items[0]["message"] == "first warn"
    assert items[1]["message"] == "boom"
    assert all("ts" in it and "module" in it for it in items)


def test_buffer_respects_maxlen():
    buf = RecentErrorsBuffer(maxlen=3)
    sink_id = install_loguru_sink(buf)
    try:
        for i in range(5):
            logger.warning(f"w{i}")
    finally:
        logger.remove(sink_id)
    items = buf.snapshot()
    assert [it["message"] for it in items] == ["w2", "w3", "w4"]


def test_get_buffer_returns_singleton():
    assert get_buffer() is get_buffer()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_recent_errors.py -v`
Expected: `ImportError` / `ModuleNotFoundError: src.open_llm_vtuber.recent_errors`.

- [ ] **Step 3: Implement `src/open_llm_vtuber/recent_errors.py`**

```python
"""In-process ring buffer of recent warning/error log records.

Installed as a loguru sink at server startup; exposed via /api/runtime/recent-errors.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from loguru import logger


class RecentErrorsBuffer:
    def __init__(self, maxlen: int = 200) -> None:
        self._dq: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = Lock()

    def add(self, record: dict[str, Any]) -> None:
        module_path = record["name"] or ""
        module = module_path.rsplit(".", 1)[-1] if module_path else ""
        extra = record.get("extra") or {}
        item = {
            "ts": record["time"].astimezone(timezone.utc).isoformat(),
            "level": record["level"].name,
            "module": module,
            "message": record["message"],
            "request_id": extra.get("request_id"),
        }
        with self._lock:
            self._dq.append(item)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._dq)


_singleton: RecentErrorsBuffer | None = None


def get_buffer() -> RecentErrorsBuffer:
    global _singleton
    if _singleton is None:
        _singleton = RecentErrorsBuffer()
    return _singleton


def install_loguru_sink(buffer: RecentErrorsBuffer | None = None) -> int:
    """Install a loguru sink that mirrors WARNING+ records into the buffer.

    Returns the sink id so callers (typically tests) can remove it.
    """
    buf = buffer or get_buffer()

    def _sink(message: Any) -> None:
        record = message.record
        buf.add(record)

    return logger.add(_sink, level="WARNING")


def reset_for_tests() -> None:
    global _singleton
    _singleton = None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_recent_errors.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint**

Run: `uv run ruff format src/open_llm_vtuber/recent_errors.py tests/test_recent_errors.py && uv run ruff check src/open_llm_vtuber/recent_errors.py tests/test_recent_errors.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/open_llm_vtuber/recent_errors.py tests/test_recent_errors.py
git commit -m "feat(admin): add recent-errors ring buffer with loguru sink"
```

---

## Task 3: Mask helper (TDD)

**Files:**
- Create: `tests/test_mask.py`
- Create: `src/open_llm_vtuber/mask.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mask.py
from src.open_llm_vtuber.mask import mask_value, mask_mapping


def test_short_strings_become_stars():
    assert mask_value("ab") == "****"


def test_long_strings_keep_last_four():
    assert mask_value("sk-abcdefghij1234") == "****1234"


def test_mask_mapping_finds_sensitive_keys():
    raw = {
        "llm_base_url": "https://api.openai.com/v1",
        "llm_api_key": "sk-1234abcdwxyz",
        "nested": {"openai_secret": "topsecret9", "ok_field": "kept"},
        "tts_token": "TKN-XYZ-9999",
        "list_field": ["plain", {"password": "p4ssw0rd!"}],
    }
    out = mask_mapping(raw)
    assert out["llm_base_url"] == "https://api.openai.com/v1"
    assert out["llm_api_key"] == "****wxyz"
    assert out["nested"]["openai_secret"] == "****ret9"
    assert out["nested"]["ok_field"] == "kept"
    assert out["tts_token"] == "****9999"
    assert out["list_field"][0] == "plain"
    assert out["list_field"][1]["password"] == "****w0rd!"


def test_non_string_sensitive_values_become_masked():
    out = mask_mapping({"api_key": 12345})
    assert out["api_key"] == "****"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_mask.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/open_llm_vtuber/mask.py`**

```python
"""Masking helpers for sensitive config values.

A key is considered sensitive when its name (case-insensitive) matches
the regex below; matched values are masked to '****<last4>' (or '****' if
the value is shorter than 5 chars or not a string).
"""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_RE = re.compile(r"(api[_-]?key|token|secret|password)", re.IGNORECASE)


def is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_RE.search(key))


def mask_value(value: Any) -> str:
    if not isinstance(value, str):
        return "****"
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


def mask_mapping(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: (mask_value(v) if is_sensitive_key(k) else mask_mapping(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [mask_mapping(v) for v in data]
    return data
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_mask.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format src/open_llm_vtuber/mask.py tests/test_mask.py
uv run ruff check src/open_llm_vtuber/mask.py tests/test_mask.py
git add src/open_llm_vtuber/mask.py tests/test_mask.py
git commit -m "feat(admin): add mask helper for sensitive config values"
```

---

## Task 4: Admin routes — `/api/health` (TDD)

**Files:**
- Create: `src/open_llm_vtuber/admin_routes.py`
- Create: `tests/test_admin_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_routes.py
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.open_llm_vtuber.admin_routes import init_admin_routes


def _make_app(snapshot_provider=None) -> FastAPI:
    app = FastAPI()
    app.include_router(
        init_admin_routes(
            snapshot_provider=snapshot_provider or (lambda: _empty_snapshot()),
        ),
    )
    return app


def _empty_snapshot():
    return {
        "asr_provider": None,
        "tts_provider": None,
        "agent_provider": None,
        "llm_provider": None,
        "llm_base_url": None,
        "llm_api_key": None,
        "host": "127.0.0.1",
        "port": 12393,
    }


@pytest.mark.asyncio
async def test_health_returns_shape():
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"ok", "degraded", "error"}
    for key in ("olv", "asr", "tts", "vad", "mcp", "ue", "platform"):
        assert key in body["components"]
        assert "status" in body["components"][key]
        assert body["components"][key]["status"] in {"ok", "busy", "warn", "err", "off"}
    assert isinstance(body["uptime_s"], int)
    assert body["version"]


@pytest.mark.asyncio
async def test_health_marks_unconfigured_components_off():
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        body = (await ac.get("/api/health")).json()
    assert body["components"]["mcp"]["status"] == "off"
    assert body["components"]["ue"]["status"] == "off"
    assert body["components"]["platform"]["status"] == "off"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_admin_routes.py -v`
Expected: `ModuleNotFoundError: src.open_llm_vtuber.admin_routes`.

- [ ] **Step 3: Implement `src/open_llm_vtuber/admin_routes.py`** (health only for now)

```python
"""Admin REST endpoints for the operations console."""

from __future__ import annotations

import socket
import time
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from .mask import mask_value
from .recent_errors import get_buffer

ComponentStatus = Literal["ok", "busy", "warn", "err", "off"]

_STARTED_AT = time.monotonic()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_version() -> str:
    try:
        import tomli

        with open("pyproject.toml", "rb") as f:
            return tomli.load(f)["project"]["version"]
    except Exception:
        return "unknown"


class ComponentHealth(BaseModel):
    status: ComponentStatus
    detail: str | None = None
    provider: str | None = None
    online_servers: int | None = None
    total_servers: int | None = None
    updated_at: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "error"]
    components: dict[str, ComponentHealth]
    version: str
    uptime_s: int


def _build_health(snapshot: dict[str, Any]) -> HealthResponse:
    now = _now_iso()
    components: dict[str, ComponentHealth] = {
        "olv": ComponentHealth(status="ok", detail="running", updated_at=now),
        "asr": ComponentHealth(
            status="ok" if snapshot.get("asr_provider") else "off",
            provider=snapshot.get("asr_provider"),
            updated_at=now,
        ),
        "tts": ComponentHealth(
            status="ok" if snapshot.get("tts_provider") else "off",
            provider=snapshot.get("tts_provider"),
            updated_at=now,
        ),
        "vad": ComponentHealth(status="ok", updated_at=now),
        "mcp": ComponentHealth(
            status="off",
            detail="not_configured",
            online_servers=0,
            total_servers=0,
            updated_at=now,
        ),
        "ue": ComponentHealth(status="off", detail="not_configured", updated_at=now),
        "platform": ComponentHealth(
            status="off", detail="not_configured", updated_at=now
        ),
    }

    overall: Literal["ok", "degraded", "error"] = "ok"
    statuses = {c.status for c in components.values()}
    if "err" in statuses:
        overall = "error"
    elif "warn" in statuses:
        overall = "degraded"

    return HealthResponse(
        status=overall,
        components=components,
        version=_read_version(),
        uptime_s=int(time.monotonic() - _STARTED_AT),
    )


def init_admin_routes(snapshot_provider: Callable[[], dict[str, Any]]) -> APIRouter:
    """Create the /api admin router.

    `snapshot_provider` returns a dict of current process configuration.
    Injected so tests can supply fakes; the real implementation reads from
    ServiceContext + the running uvicorn server.
    """

    router = APIRouter(prefix="/api")

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return _build_health(snapshot_provider())

    return router
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_admin_routes.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format src/open_llm_vtuber/admin_routes.py tests/test_admin_routes.py
uv run ruff check src/open_llm_vtuber/admin_routes.py tests/test_admin_routes.py
git add src/open_llm_vtuber/admin_routes.py tests/test_admin_routes.py
git commit -m "feat(admin): add /api/health endpoint"
```

---

## Task 5: Admin routes — `/api/runtime/snapshot` with masking (TDD)

**Files:**
- Modify: `src/open_llm_vtuber/admin_routes.py`
- Modify: `tests/test_admin_routes.py`

- [ ] **Step 1: Append failing tests to `tests/test_admin_routes.py`**

```python
@pytest.mark.asyncio
async def test_snapshot_masks_api_key():
    snapshot = {
        "asr_provider": "sherpa_onnx",
        "tts_provider": "edge_tts",
        "agent_provider": "basic_memory",
        "llm_provider": "openai_compatible_llm",
        "llm_base_url": "https://api.openai.com/v1",
        "llm_api_key": "sk-1234567890abcd",
        "host": "127.0.0.1",
        "port": 12393,
    }
    app = _make_app(snapshot_provider=lambda: snapshot)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        body = (await ac.get("/api/runtime/snapshot")).json()
    assert body["config"]["llm_api_key_masked"] == "****abcd"
    assert "llm_api_key" not in body["config"]
    assert body["config"]["llm_base_url"] == "https://api.openai.com/v1"


@pytest.mark.asyncio
async def test_snapshot_ports_include_olv():
    snapshot = {**_empty_snapshot(), "host": "127.0.0.1", "port": 12393}
    app = _make_app(snapshot_provider=lambda: snapshot)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        body = (await ac.get("/api/runtime/snapshot")).json()
    names = [p["name"] for p in body["ports"]]
    assert "OLV WebSocket / FastAPI" in names
    olv_port = next(p for p in body["ports"] if p["port"] == 12393)
    assert olv_port["bound_host"] == "127.0.0.1"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_admin_routes.py -v`
Expected: 2 newly-failing tests.

- [ ] **Step 3: Extend `admin_routes.py`**

Add (above `init_admin_routes`):

```python
class PortStatus(BaseModel):
    name: str
    port: int
    bound_host: str | None
    status: ComponentStatus


class SnapshotConfig(BaseModel):
    asr_provider: str | None = None
    tts_provider: str | None = None
    agent_provider: str | None = None
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_api_key_masked: str | None = None


class SnapshotResponse(BaseModel):
    ports: list[PortStatus]
    config: SnapshotConfig
    current_session: dict[str, Any] | None = None


def _build_snapshot(snapshot: dict[str, Any]) -> SnapshotResponse:
    olv_port = int(snapshot.get("port") or 12393)
    olv_host = snapshot.get("host") or "127.0.0.1"
    ports = [
        PortStatus(
            name="OLV WebSocket / FastAPI",
            port=olv_port,
            bound_host=olv_host,
            status="ok",
        ),
        PortStatus(name="UE WebSocket", port=10002, bound_host=None, status="off"),
        PortStatus(name="TTS Wrapper", port=50005, bound_host=None, status="off"),
    ]
    raw_key = snapshot.get("llm_api_key")
    config = SnapshotConfig(
        asr_provider=snapshot.get("asr_provider"),
        tts_provider=snapshot.get("tts_provider"),
        agent_provider=snapshot.get("agent_provider"),
        llm_provider=snapshot.get("llm_provider"),
        llm_base_url=snapshot.get("llm_base_url"),
        llm_api_key_masked=mask_value(raw_key) if raw_key else None,
    )
    return SnapshotResponse(ports=ports, config=config, current_session=None)
```

Add the route inside `init_admin_routes` after the `/health` route:

```python
    @router.get("/runtime/snapshot", response_model=SnapshotResponse)
    async def snapshot() -> SnapshotResponse:
        return _build_snapshot(snapshot_provider())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_admin_routes.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format src/open_llm_vtuber/admin_routes.py tests/test_admin_routes.py
uv run ruff check src/open_llm_vtuber/admin_routes.py tests/test_admin_routes.py
git add src/open_llm_vtuber/admin_routes.py tests/test_admin_routes.py
git commit -m "feat(admin): add /api/runtime/snapshot with masking"
```

---

## Task 6: Admin routes — `/api/runtime/recent-errors` (TDD)

**Files:**
- Modify: `src/open_llm_vtuber/admin_routes.py`
- Modify: `tests/test_admin_routes.py`

- [ ] **Step 1: Append failing tests**

```python
@pytest.mark.asyncio
async def test_recent_errors_returns_buffer_contents():
    from loguru import logger

    from src.open_llm_vtuber.recent_errors import (
        RecentErrorsBuffer,
        install_loguru_sink,
    )

    buf = RecentErrorsBuffer(maxlen=10)
    sink_id = install_loguru_sink(buf)
    try:
        logger.error("explode")
    finally:
        logger.remove(sink_id)

    app = FastAPI()
    app.include_router(
        init_admin_routes(
            snapshot_provider=_empty_snapshot,
            errors_provider=lambda: buf.snapshot(),
        ),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        body = (await ac.get("/api/runtime/recent-errors")).json()
    assert len(body["errors"]) == 1
    assert body["errors"][0]["level"] == "ERROR"
    assert body["errors"][0]["message"] == "explode"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_admin_routes.py::test_recent_errors_returns_buffer_contents -v`
Expected: TypeError (`errors_provider` unknown) or 404.

- [ ] **Step 3: Extend `admin_routes.py`**

Update the factory signature and add the route. Replace the existing `init_admin_routes` signature and body with:

```python
class RecentError(BaseModel):
    ts: str
    level: str
    module: str
    message: str
    request_id: str | None = None


class RecentErrorsResponse(BaseModel):
    errors: list[RecentError]


def init_admin_routes(
    snapshot_provider: Callable[[], dict[str, Any]],
    errors_provider: Callable[[], list[dict[str, Any]]] | None = None,
) -> APIRouter:
    """Create the /api admin router."""

    if errors_provider is None:
        errors_provider = lambda: get_buffer().snapshot()  # noqa: E731

    router = APIRouter(prefix="/api")

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return _build_health(snapshot_provider())

    @router.get("/runtime/snapshot", response_model=SnapshotResponse)
    async def snapshot() -> SnapshotResponse:
        return _build_snapshot(snapshot_provider())

    @router.get("/runtime/recent-errors", response_model=RecentErrorsResponse)
    async def recent_errors() -> RecentErrorsResponse:
        return RecentErrorsResponse(errors=[RecentError(**e) for e in errors_provider()])

    return router
```

- [ ] **Step 4: Run all admin route tests**

Run: `uv run pytest tests/test_admin_routes.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format src/open_llm_vtuber/admin_routes.py tests/test_admin_routes.py
uv run ruff check src/open_llm_vtuber/admin_routes.py tests/test_admin_routes.py
git add src/open_llm_vtuber/admin_routes.py tests/test_admin_routes.py
git commit -m "feat(admin): add /api/runtime/recent-errors"
```

---

## Task 7: Wire admin routes + sink + static mount into `server.py`

**Files:**
- Modify: `src/open_llm_vtuber/server.py`

- [ ] **Step 1: Add imports near the top (after existing `from .routes import …`)**

```python
from loguru import logger as _loguru_logger

from .admin_routes import init_admin_routes
from .recent_errors import install_loguru_sink as _install_recent_errors_sink
```

- [ ] **Step 2: Define snapshot provider helper at module scope (just above `class WebSocketServer`)**

```python
def _make_snapshot_provider(config: "Config", service_context: ServiceContext):
    def _provider() -> dict:
        sys = config.system_config
        # Pull current providers if loaded; fall back to config strings.
        asr_provider = getattr(getattr(config, "character_config", None), "asr_config", None)
        tts_provider = getattr(getattr(config, "character_config", None), "tts_config", None)
        agent_provider = getattr(getattr(config, "character_config", None), "agent_config", None)
        return {
            "asr_provider": getattr(asr_provider, "asr_model", None),
            "tts_provider": getattr(tts_provider, "tts_model", None),
            "agent_provider": getattr(agent_provider, "conversation_agent_choice", None),
            "llm_provider": _llm_provider_from(agent_provider),
            "llm_base_url": _llm_base_url_from(agent_provider),
            "llm_api_key": _llm_api_key_from(agent_provider),
            "host": getattr(sys, "host", "127.0.0.1"),
            "port": getattr(sys, "port", 12393),
        }
    return _provider


def _llm_provider_from(agent_config) -> str | None:
    if not agent_config:
        return None
    return getattr(agent_config, "llm_provider", None) or None


def _llm_base_url_from(agent_config) -> str | None:
    if not agent_config:
        return None
    cfg = getattr(agent_config, "agent_settings", None)
    return getattr(cfg, "base_url", None) if cfg else None


def _llm_api_key_from(agent_config) -> str | None:
    if not agent_config:
        return None
    cfg = getattr(agent_config, "agent_settings", None)
    return getattr(cfg, "llm_api_key", None) if cfg else None
```

Note: the helpers above touch optional attributes by `getattr` because the loaded config object differs by which agent/asr/tts profile is active. If a field is missing, the snapshot returns `None` and the health view shows `off`. This is intentional — it does not crash if the config schema changes.

- [ ] **Step 3: Install sink inside `WebSocketServer.__init__`**

Immediately after `self.app = FastAPI(...)` add:

```python
        # Install recent-errors loguru sink once per process.
        _install_recent_errors_sink()
```

- [ ] **Step 4: Include the admin router and mount `/admin` BEFORE the catch-all `/` mount**

Locate the section that mounts `/` (the `frontend` catch-all). **Before** that block, add:

```python
        # Admin REST API
        self.app.include_router(
            init_admin_routes(
                snapshot_provider=_make_snapshot_provider(config, self.default_context_cache),
            ),
        )

        # Admin frontend static (production build). Tolerate missing dir.
        admin_dist = "admin-frontend/dist"
        if os.path.isdir(admin_dist):
            self.app.mount(
                "/admin",
                CORSStaticFiles(directory=admin_dist, html=True),
                name="admin",
            )
        else:
            _loguru_logger.info(
                "admin-frontend dist not built; /admin route disabled "
                "(run `cd admin-frontend && npm install && npm run build` to enable)"
            )
```

- [ ] **Step 5: Manual smoke**

```bash
uv run python -c "from src.open_llm_vtuber.admin_routes import init_admin_routes; print('ok')"
uv run pytest tests -q
```

Expected: `ok` then `5 passed` (or however many).

Boot the server briefly:

```bash
uv run run_server.py &
SERVER=$!
sleep 6
curl -sf http://127.0.0.1:12393/api/health | head -c 400
curl -sf http://127.0.0.1:12393/api/runtime/snapshot | head -c 400
kill $SERVER
```

Expected: both curls return JSON; no errors in console.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff format src/open_llm_vtuber/server.py
uv run ruff check src/open_llm_vtuber/server.py
git add src/open_llm_vtuber/server.py
git commit -m "feat(admin): wire admin routes, sink, and /admin static mount"
```

---

## Task 8: Frontend workspace scaffold

**Files:**
- Create: `admin-frontend/package.json`
- Create: `admin-frontend/tsconfig.json`
- Create: `admin-frontend/tsconfig.node.json`
- Create: `admin-frontend/vite.config.ts`
- Create: `admin-frontend/index.html`
- Create: `admin-frontend/.gitignore`
- Create: `admin-frontend/src/main.tsx`
- Create: `admin-frontend/src/App.tsx`
- Create: `admin-frontend/src/index.css`

- [ ] **Step 1: Create `admin-frontend/package.json`**

```json
{
  "name": "olv-admin-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc -b --noEmit",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "format": "prettier --write .",
    "format:check": "prettier --check .",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.50.0",
    "i18next": "^23.12.0",
    "lucide-react": "^0.400.0",
    "pixi-live2d-display": "^0.4.0",
    "pixi.js": "^7.4.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-i18next": "^14.1.2",
    "react-router-dom": "^6.24.0",
    "zustand": "^4.5.4"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.6",
    "@testing-library/react": "^16.0.0",
    "@types/node": "^20.14.0",
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@typescript-eslint/eslint-plugin": "^7.13.0",
    "@typescript-eslint/parser": "^7.13.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.19",
    "eslint": "^8.57.0",
    "eslint-plugin-react-hooks": "^4.6.2",
    "eslint-plugin-react-refresh": "^0.4.7",
    "jsdom": "^24.1.0",
    "postcss": "^8.4.38",
    "prettier": "^3.3.2",
    "prettier-plugin-tailwindcss": "^0.6.5",
    "tailwindcss": "^3.4.4",
    "typescript": "^5.4.5",
    "vite": "^5.3.1",
    "vitest": "^1.6.0"
  }
}
```

- [ ] **Step 2: Create `admin-frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": false,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] },
    "types": ["vite/client", "vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 3: Create `admin-frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts", "vitest.config.ts", "tailwind.config.ts", "postcss.config.js"]
}
```

- [ ] **Step 4: Create `admin-frontend/vite.config.ts`**

```ts
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const OLV_URL = "http://127.0.0.1:12393";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/admin/" : "/",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": OLV_URL,
      "/client-ws": { target: OLV_URL, ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
}));
```

- [ ] **Step 5: Create `admin-frontend/index.html`**

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1.0" />
    <title>Open-LLM-VTuber 控制台</title>
  </head>
  <body class="bg-slate-50 text-slate-900 antialiased">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create `admin-frontend/.gitignore`**

```
node_modules
dist
.eslintcache
*.log
.DS_Store
```

- [ ] **Step 7: Stub `src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 8: Stub `src/App.tsx`**

```tsx
export default function App() {
  return <div className="p-8 text-lg">admin-frontend boot</div>;
}
```

- [ ] **Step 9: Stub `src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 10: Install + smoke**

```bash
cd admin-frontend
npm install
npm run typecheck
npm run build
```

Expected: type check passes; `dist/` produced; bundle warning under 800KB (stub will be tiny).

- [ ] **Step 11: Commit**

```bash
git add admin-frontend/.gitignore admin-frontend/package.json admin-frontend/tsconfig*.json admin-frontend/vite.config.ts admin-frontend/index.html admin-frontend/src
git commit -m "chore(admin-frontend): scaffold Vite + React + TS workspace"
```

---

## Task 9: Tailwind + shadcn setup

**Files:**
- Create: `admin-frontend/tailwind.config.ts`
- Create: `admin-frontend/postcss.config.js`
- Create: `admin-frontend/components.json`
- Modify: `admin-frontend/src/index.css`
- Create: `admin-frontend/src/lib/utils.ts`

- [ ] **Step 1: `tailwind.config.ts`**

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        status: {
          ok: "hsl(160 60% 42%)",
          busy: "hsl(214 90% 52%)",
          warn: "hsl(33 95% 55%)",
          err: "hsl(0 82% 56%)",
          off: "hsl(220 12% 65%)",
        },
        border: "hsl(214 32% 91%)",
        input: "hsl(214 32% 91%)",
        ring: "hsl(214 90% 52%)",
        background: "hsl(0 0% 100%)",
        foreground: "hsl(222 47% 11%)",
        primary: { DEFAULT: "hsl(214 90% 52%)", foreground: "hsl(0 0% 100%)" },
        secondary: { DEFAULT: "hsl(210 40% 96%)", foreground: "hsl(222 47% 11%)" },
        destructive: { DEFAULT: "hsl(0 82% 56%)", foreground: "hsl(0 0% 100%)" },
        muted: { DEFAULT: "hsl(210 40% 96%)", foreground: "hsl(215 16% 47%)" },
        accent: { DEFAULT: "hsl(210 40% 96%)", foreground: "hsl(222 47% 11%)" },
        card: { DEFAULT: "hsl(0 0% 100%)", foreground: "hsl(222 47% 11%)" },
      },
      borderRadius: { sm: "4px", DEFAULT: "6px", md: "8px", lg: "10px" },
    },
  },
  plugins: [],
};

export default config;
```

- [ ] **Step 2: `postcss.config.js`**

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 3: `components.json` (shadcn config)**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "src/index.css",
    "baseColor": "neutral",
    "cssVariables": false,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 4: `src/lib/utils.ts`**

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 5: Add the two utils helper deps**

In `admin-frontend/` run:

```bash
npm install clsx tailwind-merge class-variance-authority
```

- [ ] **Step 6: Use shadcn CLI to install the needed components**

```bash
npx --yes shadcn@latest init -d
npx --yes shadcn@latest add button card badge tabs separator dialog sheet dropdown-menu tooltip skeleton input textarea scroll-area
```

If the init prompt insists on overwriting `tailwind.config.ts` or `components.json`, choose "no" — they are already correct.

- [ ] **Step 7: Verify build**

```bash
npm run typecheck
npm run build
```

Expected: clean, dist produced.

- [ ] **Step 8: Commit**

```bash
git add admin-frontend/tailwind.config.ts admin-frontend/postcss.config.js admin-frontend/components.json admin-frontend/src/index.css admin-frontend/src/lib/utils.ts admin-frontend/src/components admin-frontend/package.json admin-frontend/package-lock.json
git commit -m "chore(admin-frontend): set up Tailwind + shadcn/ui"
```

---

## Task 10: ESLint, Prettier, Vitest config

**Files:**
- Create: `admin-frontend/.eslintrc.cjs`
- Create: `admin-frontend/.prettierrc`
- Create: `admin-frontend/vitest.config.ts`
- Create: `admin-frontend/src/__tests__/setup.ts`

- [ ] **Step 1: `.eslintrc.cjs`**

```js
module.exports = {
  root: true,
  env: { browser: true, es2020: true, node: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
  ],
  ignorePatterns: ["dist", "node_modules", ".eslintrc.cjs"],
  parser: "@typescript-eslint/parser",
  plugins: ["react-refresh"],
  rules: {
    "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
    "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
  },
};
```

- [ ] **Step 2: `.prettierrc`**

```json
{
  "semi": true,
  "singleQuote": false,
  "trailingComma": "all",
  "printWidth": 100,
  "plugins": ["prettier-plugin-tailwindcss"]
}
```

- [ ] **Step 3: `vitest.config.ts`**

```ts
import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
    css: false,
  },
});
```

- [ ] **Step 4: `src/__tests__/setup.ts`**

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 5: Smoke run**

```bash
npm run lint
npm run format:check || npm run format
npm run test
```

Expected: lint clean, prettier clean, vitest "no test files found" exits 0.

- [ ] **Step 6: Commit**

```bash
git add admin-frontend/.eslintrc.cjs admin-frontend/.prettierrc admin-frontend/vitest.config.ts admin-frontend/src/__tests__/setup.ts
git commit -m "chore(admin-frontend): add eslint, prettier, vitest config"
```

---

## Task 11: WS protocol types + ws-client (TDD)

**Files:**
- Create: `admin-frontend/src/lib/ws-protocol.ts`
- Create: `admin-frontend/src/lib/ws-client.ts`
- Create: `admin-frontend/src/__tests__/lib/ws-client.test.ts`

- [ ] **Step 1: Write `ws-protocol.ts`**

```ts
// Mirrors src/open_llm_vtuber/websocket_handler.py MessageType + WSMessage.
// Verified at design time against the running OLV protocol.

export type ControlText =
  | "start-mic"
  | "interrupt"
  | "mic-audio-end"
  | "conversation-chain-start"
  | "conversation-chain-end";

export type InboundMessage =
  | { type: "full-text"; text: string; role?: "user" | "assistant" }
  | {
      type: "audio";
      audio: string | null;
      volumes: number[];
      slice_length: number;
      display_text?: { text?: string; name?: string } | null;
      actions?: { expressions?: number[]; motions?: string[] } | null;
      forwarded?: boolean;
    }
  | { type: "set-model-and-conf"; [k: string]: unknown }
  | { type: "new-history-created"; history_uid: string }
  | { type: "history-data"; messages: Array<{ role: string; content: string }>; history_uid: string }
  | { type: "history-list"; histories: Array<{ uid: string; latest_message?: string; timestamp?: string }> }
  | { type: "user-input-transcription"; text: string }
  | { type: "control"; text: ControlText }
  | { type: "error"; message: string; code?: string };

export type OutboundMessage =
  | { type: "text-input"; text: string }
  | { type: "mic-audio-data"; audio: number[] }
  | { type: "mic-audio-end" }
  | { type: "interrupt-signal" }
  | { type: "fetch-history-list" }
  | { type: "fetch-history"; history_uid: string }
  | { type: "create-new-history" }
  | { type: "audio-play-start"; display_text?: unknown }
  | { type: "heartbeat" };

export type AnyMessage = InboundMessage | OutboundMessage;
```

- [ ] **Step 2: Write failing test for the client**

```ts
// src/__tests__/lib/ws-client.test.ts
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { OlvWsClient } from "@/lib/ws-client";

class MockWebSocket {
  public static instances: MockWebSocket[] = [];
  public readyState = 0;
  public onopen: ((e?: unknown) => void) | null = null;
  public onclose: ((e?: unknown) => void) | null = null;
  public onerror: ((e?: unknown) => void) | null = null;
  public onmessage: ((e: { data: string }) => void) | null = null;
  public sent: string[] = [];

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  triggerOpen() {
    this.readyState = 1;
    this.onopen?.();
  }
  triggerMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

describe("OlvWsClient", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.useFakeTimers();
    (globalThis as unknown as { WebSocket: typeof MockWebSocket }).WebSocket =
      MockWebSocket as unknown as typeof MockWebSocket;
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  test("dispatches messages by type", () => {
    const client = new OlvWsClient("ws://x/client-ws");
    client.connect();
    const sock = MockWebSocket.instances[0];
    sock.triggerOpen();

    const audioHandler = vi.fn();
    client.on("audio", audioHandler);

    sock.triggerMessage({ type: "audio", audio: "x", volumes: [], slice_length: 20 });
    expect(audioHandler).toHaveBeenCalledTimes(1);
  });

  test("queues sends until connected", () => {
    const client = new OlvWsClient("ws://x/client-ws");
    client.connect();
    client.send({ type: "heartbeat" });

    const sock = MockWebSocket.instances[0];
    expect(sock.sent).toEqual([]);

    sock.triggerOpen();
    expect(sock.sent.length).toBe(1);
    expect(JSON.parse(sock.sent[0])).toEqual({ type: "heartbeat" });
  });

  test("reconnects with exponential backoff capped at 30s", () => {
    const client = new OlvWsClient("ws://x/client-ws");
    client.connect();
    let sock = MockWebSocket.instances[0];
    sock.close();
    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances.length).toBe(2);
    sock = MockWebSocket.instances[1];
    sock.close();
    vi.advanceTimersByTime(2000);
    expect(MockWebSocket.instances.length).toBe(3);
  });

  test("heartbeat timeout triggers reconnect", () => {
    const client = new OlvWsClient("ws://x/client-ws", { heartbeatMs: 25_000, idleTimeoutMs: 60_000 });
    client.connect();
    const sock = MockWebSocket.instances[0];
    sock.triggerOpen();
    vi.advanceTimersByTime(61_000);
    expect(MockWebSocket.instances.length).toBeGreaterThan(1);
  });
});
```

- [ ] **Step 3: Run test to verify failure**

```bash
npm run test -- src/__tests__/lib/ws-client.test.ts
```

Expected: cannot resolve `@/lib/ws-client`.

- [ ] **Step 4: Implement `src/lib/ws-client.ts`**

```ts
import type { AnyMessage, InboundMessage, OutboundMessage } from "./ws-protocol";

type Handler<T extends InboundMessage["type"]> = (
  msg: Extract<InboundMessage, { type: T }>,
) => void;

export interface OlvWsClientOptions {
  heartbeatMs?: number;
  idleTimeoutMs?: number;
  maxBackoffMs?: number;
}

export class OlvWsClient {
  private socket: WebSocket | null = null;
  private handlers = new Map<string, Set<(msg: InboundMessage) => void>>();
  private outboundQueue: OutboundMessage[] = [];
  private backoffMs = 1000;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;

  constructor(
    private readonly url: string,
    private readonly opts: Required<OlvWsClientOptions> = {
      heartbeatMs: 25_000,
      idleTimeoutMs: 60_000,
      maxBackoffMs: 30_000,
    },
  ) {}

  connect(): void {
    this.intentionallyClosed = false;
    const sock = new WebSocket(this.url);
    this.socket = sock;
    sock.onopen = () => {
      this.backoffMs = 1000;
      this.flushQueue();
      this.startHeartbeat();
      this.resetIdleTimer();
    };
    sock.onmessage = (e) => {
      this.resetIdleTimer();
      try {
        const msg = JSON.parse(e.data) as InboundMessage;
        const set = this.handlers.get(msg.type);
        if (set) set.forEach((h) => h(msg));
      } catch {
        // ignore malformed frames
      }
    };
    sock.onclose = () => this.scheduleReconnect();
    sock.onerror = () => {
      // onclose follows; nothing to do here
    };
  }

  send(msg: OutboundMessage): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(msg));
    } else {
      this.outboundQueue.push(msg);
    }
  }

  on<T extends InboundMessage["type"]>(type: T, handler: Handler<T>): () => void {
    let set = this.handlers.get(type);
    if (!set) {
      set = new Set();
      this.handlers.set(type, set);
    }
    set.add(handler as (msg: InboundMessage) => void);
    return () => set!.delete(handler as (msg: InboundMessage) => void);
  }

  close(): void {
    this.intentionallyClosed = true;
    this.stopHeartbeat();
    this.clearIdleTimer();
    this.socket?.close();
    this.socket = null;
  }

  private flushQueue(): void {
    while (this.outboundQueue.length > 0 && this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(this.outboundQueue.shift()));
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: "heartbeat" });
    }, this.opts.heartbeatMs);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  private resetIdleTimer(): void {
    this.clearIdleTimer();
    this.idleTimer = setTimeout(() => {
      this.socket?.close();
    }, this.opts.idleTimeoutMs);
  }

  private clearIdleTimer(): void {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = null;
  }

  private scheduleReconnect(): void {
    this.stopHeartbeat();
    this.clearIdleTimer();
    this.socket = null;
    if (this.intentionallyClosed) return;
    const delay = this.backoffMs;
    this.backoffMs = Math.min(this.backoffMs * 2, this.opts.maxBackoffMs);
    setTimeout(() => this.connect(), delay);
  }
}

export type { AnyMessage };
```

- [ ] **Step 5: Run tests**

```bash
npm run test -- src/__tests__/lib/ws-client.test.ts
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add admin-frontend/src/lib/ws-protocol.ts admin-frontend/src/lib/ws-client.ts admin-frontend/src/__tests__
git commit -m "feat(admin-frontend): add WS client with reconnect, heartbeat, queued send"
```

---

## Task 12: Frontend mask utility (TDD)

**Files:**
- Create: `admin-frontend/src/lib/mask.ts`
- Create: `admin-frontend/src/__tests__/lib/mask.test.ts`

(The backend already masks; the frontend mask is only used for client-side display of values typed locally — kept tiny.)

- [ ] **Step 1: Failing test**

```ts
import { describe, expect, test } from "vitest";
import { maskApiKeyDisplay } from "@/lib/mask";

describe("maskApiKeyDisplay", () => {
  test("returns **** for short", () => {
    expect(maskApiKeyDisplay("ab")).toBe("****");
  });
  test("returns ****<last4>", () => {
    expect(maskApiKeyDisplay("sk-abcdef1234")).toBe("****1234");
  });
  test("handles null/undefined", () => {
    expect(maskApiKeyDisplay(null)).toBe("");
    expect(maskApiKeyDisplay(undefined)).toBe("");
  });
});
```

- [ ] **Step 2: Run, see failure, then implement `src/lib/mask.ts`**

```ts
export function maskApiKeyDisplay(value: string | null | undefined): string {
  if (value == null) return "";
  if (value.length <= 4) return "****";
  return `****${value.slice(-4)}`;
}
```

- [ ] **Step 3: Run + commit**

```bash
npm run test -- src/__tests__/lib/mask.test.ts
git add admin-frontend/src/lib/mask.ts admin-frontend/src/__tests__/lib/mask.test.ts
git commit -m "feat(admin-frontend): add maskApiKeyDisplay"
```

---

## Task 13: API client + TanStack hooks

**Files:**
- Create: `admin-frontend/src/lib/api-client.ts`
- Create: `admin-frontend/src/hooks/use-health.ts`
- Create: `admin-frontend/src/hooks/use-runtime-snapshot.ts`
- Create: `admin-frontend/src/hooks/use-recent-errors.ts`

- [ ] **Step 1: `src/lib/api-client.ts`**

```ts
export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export interface HealthComponent {
  status: "ok" | "busy" | "warn" | "err" | "off";
  detail?: string | null;
  provider?: string | null;
  online_servers?: number | null;
  total_servers?: number | null;
  updated_at: string;
}

export interface HealthResponse {
  status: "ok" | "degraded" | "error";
  components: {
    olv: HealthComponent;
    asr: HealthComponent;
    tts: HealthComponent;
    vad: HealthComponent;
    mcp: HealthComponent;
    ue: HealthComponent;
    platform: HealthComponent;
  };
  version: string;
  uptime_s: number;
}

export interface PortStatus {
  name: string;
  port: number;
  bound_host: string | null;
  status: HealthComponent["status"];
}

export interface SnapshotResponse {
  ports: PortStatus[];
  config: {
    asr_provider: string | null;
    tts_provider: string | null;
    agent_provider: string | null;
    llm_provider: string | null;
    llm_base_url: string | null;
    llm_api_key_masked: string | null;
  };
  current_session: unknown | null;
}

export interface RecentError {
  ts: string;
  level: string;
  module: string;
  message: string;
  request_id: string | null;
}

export interface RecentErrorsResponse {
  errors: RecentError[];
}
```

- [ ] **Step 2: `src/hooks/use-health.ts`**

```ts
import { useQuery } from "@tanstack/react-query";
import { getJson, type HealthResponse } from "@/lib/api-client";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => getJson<HealthResponse>("/api/health"),
    refetchInterval: 5000,
  });
}
```

- [ ] **Step 3: `src/hooks/use-runtime-snapshot.ts`**

```ts
import { useQuery } from "@tanstack/react-query";
import { getJson, type SnapshotResponse } from "@/lib/api-client";

export function useRuntimeSnapshot() {
  return useQuery({
    queryKey: ["snapshot"],
    queryFn: () => getJson<SnapshotResponse>("/api/runtime/snapshot"),
    refetchInterval: 30_000,
  });
}
```

- [ ] **Step 4: `src/hooks/use-recent-errors.ts`**

```ts
import { useQuery } from "@tanstack/react-query";
import { getJson, type RecentErrorsResponse } from "@/lib/api-client";

export function useRecentErrors() {
  return useQuery({
    queryKey: ["recent-errors"],
    queryFn: () => getJson<RecentErrorsResponse>("/api/runtime/recent-errors"),
    refetchInterval: 10_000,
  });
}
```

- [ ] **Step 5: typecheck + commit**

```bash
npm run typecheck
git add admin-frontend/src/lib/api-client.ts admin-frontend/src/hooks
git commit -m "feat(admin-frontend): add REST hooks for health/snapshot/recent-errors"
```

---

## Task 14: Zustand stores

**Files:**
- Create: `admin-frontend/src/stores/connection-store.ts`
- Create: `admin-frontend/src/stores/session-store.ts`
- Create: `admin-frontend/src/stores/settings-store.ts`

- [ ] **Step 1: `connection-store.ts`**

```ts
import { create } from "zustand";

export type WsStatus = "idle" | "connecting" | "open" | "closed" | "error";

interface ConnectionState {
  wsStatus: WsStatus;
  wsLastError: string | null;
  clientUid: string | null;
  heartbeatAt: number | null;
  setStatus: (s: WsStatus) => void;
  setError: (e: string | null) => void;
  setClientUid: (uid: string | null) => void;
  bumpHeartbeat: () => void;
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  wsStatus: "idle",
  wsLastError: null,
  clientUid: null,
  heartbeatAt: null,
  setStatus: (s) => set({ wsStatus: s }),
  setError: (e) => set({ wsLastError: e }),
  setClientUid: (uid) => set({ clientUid: uid }),
  bumpHeartbeat: () => set({ heartbeatAt: Date.now() }),
}));
```

- [ ] **Step 2: `session-store.ts`**

```ts
import { create } from "zustand";

export type BroadcastState =
  | "idle"
  | "listening"
  | "recognizing"
  | "thinking"
  | "speaking"
  | "interrupted"
  | "completed"
  | "error";

export interface AudioSegment {
  sliceId: string;
  durationMs: number;
}

export type Message =
  | { kind: "user-text"; id: string; text: string; ts: number }
  | { kind: "user-voice"; id: string; text: string; confidence?: number; ts: number }
  | {
      kind: "assistant";
      id: string;
      text: string;
      ts: number;
      broadcastDone: boolean;
      audioSegments: AudioSegment[];
    }
  | { kind: "transition"; id: string; text: string; ts: number }
  | { kind: "error"; id: string; text: string; ts: number; code?: string };

export interface HistoryItem {
  uid: string;
  title: string;
  summary: string;
  updatedAt: number;
  status: "completed" | "in_progress" | "interrupted" | "error";
}

interface SessionState {
  currentSessionId: string | null;
  messages: Message[];
  broadcastState: BroadcastState;
  historyList: HistoryItem[];
  setSession: (id: string | null) => void;
  appendMessage: (m: Message) => void;
  clearMessages: () => void;
  setBroadcastState: (s: BroadcastState) => void;
  setHistoryList: (h: HistoryItem[]) => void;
  markCurrentAssistantInterrupted: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  currentSessionId: null,
  messages: [],
  broadcastState: "idle",
  historyList: [],
  setSession: (id) => set({ currentSessionId: id }),
  appendMessage: (m) => set((st) => ({ messages: [...st.messages, m] })),
  clearMessages: () => set({ messages: [] }),
  setBroadcastState: (s) => set({ broadcastState: s }),
  setHistoryList: (h) => set({ historyList: h }),
  markCurrentAssistantInterrupted: () =>
    set((st) => {
      const last = [...st.messages];
      for (let i = last.length - 1; i >= 0; i--) {
        if (last[i].kind === "assistant") {
          last[i] = { ...(last[i] as Extract<Message, { kind: "assistant" }>), broadcastDone: false };
          break;
        }
      }
      return { messages: last };
    }),
}));
```

- [ ] **Step 3: `settings-store.ts`**

```ts
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SettingsState {
  locale: "zh-CN" | "en-US";
  live2dPreviewEnabled: boolean;
  audioMuted: boolean;
  setLocale: (l: SettingsState["locale"]) => void;
  setLive2dPreviewEnabled: (v: boolean) => void;
  setAudioMuted: (v: boolean) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      locale: "zh-CN",
      live2dPreviewEnabled: false,
      audioMuted: false,
      setLocale: (locale) => set({ locale }),
      setLive2dPreviewEnabled: (live2dPreviewEnabled) => set({ live2dPreviewEnabled }),
      setAudioMuted: (audioMuted) => set({ audioMuted }),
    }),
    { name: "olv-admin-settings" },
  ),
);
```

- [ ] **Step 4: typecheck + commit**

```bash
npm run typecheck
git add admin-frontend/src/stores
git commit -m "feat(admin-frontend): add zustand stores (connection, session, settings)"
```

---

## Task 15: i18n setup

**Files:**
- Create: `admin-frontend/src/i18n.ts`
- Create: `admin-frontend/src/locales/zh-CN/{common,overview,conversation}.json`
- Create: `admin-frontend/src/locales/en-US/{common,overview,conversation}.json`

- [ ] **Step 1: `src/i18n.ts`**

```ts
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import zhCommon from "./locales/zh-CN/common.json";
import zhOverview from "./locales/zh-CN/overview.json";
import zhConversation from "./locales/zh-CN/conversation.json";
import enCommon from "./locales/en-US/common.json";
import enOverview from "./locales/en-US/overview.json";
import enConversation from "./locales/en-US/conversation.json";

i18n.use(initReactI18next).init({
  resources: {
    "zh-CN": { common: zhCommon, overview: zhOverview, conversation: zhConversation },
    "en-US": { common: enCommon, overview: enOverview, conversation: enConversation },
  },
  lng: "zh-CN",
  fallbackLng: "zh-CN",
  defaultNS: "common",
  interpolation: { escapeValue: false },
});

export default i18n;
```

- [ ] **Step 2: `src/locales/zh-CN/common.json`**

```json
{
  "app": { "title": "Open-LLM-VTuber 控制台" },
  "nav": {
    "overview": "总览",
    "conversation": "对话控制台",
    "avatars": "数字人",
    "mcp": "MCP 工具",
    "config": "配置",
    "logs": "日志与调试",
    "comingSoon": "敬请期待"
  },
  "actions": {
    "refresh": "刷新",
    "alerts": "告警",
    "settings": "设置",
    "test": "测试",
    "interrupt": "打断播报",
    "send": "发送",
    "newSession": "新建会话",
    "expand": "展开",
    "collapse": "折叠"
  },
  "status": {
    "ok": "正常",
    "busy": "处理中",
    "warn": "告警",
    "err": "异常",
    "off": "未启用",
    "allOk": "全部正常",
    "warningCount": "{{count}} 个组件告警",
    "errorCount": "{{count}} 个组件异常",
    "allOff": "未配置"
  },
  "fallback": {
    "platformTimeout": "客户平台响应超时，本轮回答暂时无法完成。可以稍后重试。",
    "mcpOffline": "关联工具当前离线，系统将使用已有上下文进行回答。",
    "ueDisconnected": "UE 数字人客户端未连接，音频和字幕可能无法同步展示。",
    "asrFailed": "没有识别到清晰语音，请靠近麦克风后重试。",
    "noPermission": "当前问题涉及受限内容，系统无法展示相关结果。",
    "comingSoon": "待接入"
  }
}
```

- [ ] **Step 3: `src/locales/zh-CN/overview.json`**

```json
{
  "title": "总览",
  "subtitle": "服务健康 / 端口 / 链路 / 最近异常 / 快速测试",
  "cards": {
    "olv": "OLV 服务",
    "asr": "语音输入 / ASR",
    "tts": "TTS",
    "mcp": "MCP",
    "ue": "UE 数字人",
    "platform": "客户平台"
  },
  "ports": {
    "title": "端口状态",
    "name": "名称",
    "port": "端口",
    "boundHost": "绑定地址",
    "status": "状态",
    "customMcpEmpty": "暂无配置"
  },
  "errors": {
    "title": "最近异常",
    "empty": "暂无异常",
    "time": "时间",
    "module": "模块",
    "level": "级别",
    "summary": "摘要"
  },
  "quickTest": {
    "title": "快速测试",
    "text": "测试文本问答",
    "voice": "测试语音输入",
    "tts": "测试 TTS",
    "mcp": "测试 MCP 工具",
    "ue": "测试 UE 连接"
  }
}
```

- [ ] **Step 4: `src/locales/zh-CN/conversation.json`**

```json
{
  "title": "对话控制台",
  "history": {
    "search": "搜索会话",
    "empty": "暂无会话"
  },
  "session": {
    "messages": "{{count}} 条消息",
    "untitled": "未命名会话"
  },
  "broadcast": {
    "idle": "待输入",
    "listening": "录音中",
    "recognizing": "识别中",
    "thinking": "思考中",
    "speaking": "播报中",
    "interrupted": "已打断",
    "completed": "已完成",
    "error": "异常"
  },
  "composer": {
    "placeholder": "输入要让数字人回答的问题",
    "send": "发送",
    "interrupt": "打断播报"
  },
  "stage": {
    "live2dCollapsed": "Live2D 预览已折叠 · {{action}}",
    "live2dFailed": "Live2D 模型加载失败 · {{action}}",
    "audioQueue": "{{count}} 待播片段",
    "volume": "音量",
    "mute": "静音"
  },
  "process": {
    "title": "查看过程",
    "empty": "暂无过程信息"
  }
}
```

- [ ] **Step 5: Mirror English copies**

Create `src/locales/en-US/common.json`:

```json
{
  "app": { "title": "Open-LLM-VTuber Console" },
  "nav": {
    "overview": "Overview",
    "conversation": "Conversation",
    "avatars": "Avatars",
    "mcp": "MCP Tools",
    "config": "Settings",
    "logs": "Logs & Debug",
    "comingSoon": "Coming soon"
  },
  "actions": {
    "refresh": "Refresh",
    "alerts": "Alerts",
    "settings": "Settings",
    "test": "Test",
    "interrupt": "Interrupt",
    "send": "Send",
    "newSession": "New session",
    "expand": "Expand",
    "collapse": "Collapse"
  },
  "status": {
    "ok": "OK",
    "busy": "Busy",
    "warn": "Warning",
    "err": "Error",
    "off": "Disabled",
    "allOk": "All systems normal",
    "warningCount": "{{count}} component(s) warning",
    "errorCount": "{{count}} component(s) error",
    "allOff": "Not configured"
  },
  "fallback": {
    "platformTimeout": "Customer platform timed out. Please retry later.",
    "mcpOffline": "MCP tools offline; falling back to existing context.",
    "ueDisconnected": "UE client disconnected; audio and captions may be out of sync.",
    "asrFailed": "No clear speech recognized; move closer to the mic and retry.",
    "noPermission": "Restricted content; cannot display the result.",
    "comingSoon": "Not wired"
  }
}
```

Create `src/locales/en-US/overview.json`:

```json
{
  "title": "Overview",
  "subtitle": "Health / Ports / Channels / Recent errors / Quick tests",
  "cards": {
    "olv": "OLV Service",
    "asr": "Speech Input / ASR",
    "tts": "TTS",
    "mcp": "MCP",
    "ue": "UE Avatar",
    "platform": "Customer Platform"
  },
  "ports": {
    "title": "Port status",
    "name": "Name",
    "port": "Port",
    "boundHost": "Bound host",
    "status": "Status",
    "customMcpEmpty": "No custom MCP ports configured"
  },
  "errors": {
    "title": "Recent errors",
    "empty": "No recent errors",
    "time": "Time",
    "module": "Module",
    "level": "Level",
    "summary": "Summary"
  },
  "quickTest": {
    "title": "Quick test",
    "text": "Test text Q&A",
    "voice": "Test voice input",
    "tts": "Test TTS",
    "mcp": "Test MCP tool",
    "ue": "Test UE connection"
  }
}
```

Create `src/locales/en-US/conversation.json`:

```json
{
  "title": "Conversation",
  "history": { "search": "Search sessions", "empty": "No sessions yet" },
  "session": { "messages": "{{count}} messages", "untitled": "Untitled session" },
  "broadcast": {
    "idle": "Idle",
    "listening": "Listening",
    "recognizing": "Recognizing",
    "thinking": "Thinking",
    "speaking": "Speaking",
    "interrupted": "Interrupted",
    "completed": "Done",
    "error": "Error"
  },
  "composer": {
    "placeholder": "Type a question for the digital human",
    "send": "Send",
    "interrupt": "Interrupt"
  },
  "stage": {
    "live2dCollapsed": "Live2D preview collapsed · {{action}}",
    "live2dFailed": "Live2D model failed to load · {{action}}",
    "audioQueue": "{{count}} queued slices",
    "volume": "Volume",
    "mute": "Mute"
  },
  "process": { "title": "View process", "empty": "No process info yet" }
}
```

- [ ] **Step 6: typecheck + commit**

```bash
npm run typecheck
git add admin-frontend/src/i18n.ts admin-frontend/src/locales
git commit -m "feat(admin-frontend): add i18n with zh-CN/en-US"
```

---

## Task 16: AppShell, TopBar, SideNav, GlobalHealthBadge (with derivation test)

**Files:**
- Create: `admin-frontend/src/components/status/StatusBadge.tsx`
- Create: `admin-frontend/src/components/status/GlobalHealthBadge.tsx`
- Create: `admin-frontend/src/components/shell/AppShell.tsx`
- Create: `admin-frontend/src/components/shell/TopBar.tsx`
- Create: `admin-frontend/src/components/shell/SideNav.tsx`
- Create: `admin-frontend/src/__tests__/components/global-health-badge.test.tsx`

- [ ] **Step 1: Write failing test for GlobalHealthBadge derivation**

```tsx
// src/__tests__/components/global-health-badge.test.tsx
import { describe, expect, test } from "vitest";
import { deriveGlobalHealth } from "@/components/status/GlobalHealthBadge";
import type { HealthResponse } from "@/lib/api-client";

function makeHealth(over: Partial<HealthResponse["components"]> = {}): HealthResponse {
  const ok = { status: "ok" as const, updated_at: "" };
  return {
    status: "ok",
    version: "0",
    uptime_s: 1,
    components: {
      olv: ok,
      asr: ok,
      tts: ok,
      vad: ok,
      mcp: { status: "off", updated_at: "" },
      ue: { status: "off", updated_at: "" },
      platform: { status: "off", updated_at: "" },
      ...over,
    },
  };
}

describe("deriveGlobalHealth", () => {
  test("all-ok wins when only off remainders", () => {
    expect(deriveGlobalHealth(makeHealth()).kind).toBe("ok");
  });
  test("err dominates", () => {
    const h = makeHealth({ asr: { status: "err", updated_at: "" } });
    expect(deriveGlobalHealth(h)).toEqual({ kind: "err", count: 1 });
  });
  test("warn shows when no err but at least one warn", () => {
    const h = makeHealth({ tts: { status: "warn", updated_at: "" } });
    expect(deriveGlobalHealth(h)).toEqual({ kind: "warn", count: 1 });
  });
  test("all-off → off", () => {
    const allOff = { status: "off" as const, updated_at: "" };
    const h: HealthResponse = {
      status: "ok",
      version: "0",
      uptime_s: 1,
      components: {
        olv: allOff,
        asr: allOff,
        tts: allOff,
        vad: allOff,
        mcp: allOff,
        ue: allOff,
        platform: allOff,
      },
    };
    expect(deriveGlobalHealth(h).kind).toBe("off");
  });
});
```

- [ ] **Step 2: Implement `StatusBadge.tsx`**

```tsx
import { cn } from "@/lib/utils";

export type StatusKind = "ok" | "busy" | "warn" | "err" | "off";

const classes: Record<StatusKind, string> = {
  ok: "bg-status-ok/15 text-status-ok",
  busy: "bg-status-busy/15 text-status-busy",
  warn: "bg-status-warn/15 text-status-warn",
  err: "bg-status-err/15 text-status-err",
  off: "bg-status-off/15 text-status-off",
};

const dotClasses: Record<StatusKind, string> = {
  ok: "bg-status-ok",
  busy: "bg-status-busy animate-pulse",
  warn: "bg-status-warn",
  err: "bg-status-err",
  off: "bg-status-off",
};

export function StatusBadge({ status, label }: { status: StatusKind; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium",
        classes[status],
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", dotClasses[status])} />
      {label}
    </span>
  );
}
```

- [ ] **Step 3: Implement `GlobalHealthBadge.tsx`**

```tsx
import { useTranslation } from "react-i18next";
import { useHealth } from "@/hooks/use-health";
import { StatusBadge, type StatusKind } from "./StatusBadge";
import type { HealthResponse } from "@/lib/api-client";

export type GlobalHealth =
  | { kind: "ok"; count: number }
  | { kind: "warn"; count: number }
  | { kind: "err"; count: number }
  | { kind: "off"; count: number };

export function deriveGlobalHealth(health: HealthResponse): GlobalHealth {
  const statuses = Object.values(health.components).map((c) => c.status);
  const err = statuses.filter((s) => s === "err").length;
  if (err > 0) return { kind: "err", count: err };
  const warn = statuses.filter((s) => s === "warn").length;
  if (warn > 0) return { kind: "warn", count: warn };
  const nonOff = statuses.filter((s) => s !== "off").length;
  if (nonOff === 0) return { kind: "off", count: statuses.length };
  return { kind: "ok", count: nonOff };
}

export function GlobalHealthBadge() {
  const { t } = useTranslation();
  const { data, isLoading } = useHealth();
  if (isLoading || !data) {
    return <StatusBadge status="off" label="..." />;
  }
  const g = deriveGlobalHealth(data);
  const status: StatusKind =
    g.kind === "ok" ? "ok" : g.kind === "warn" ? "warn" : g.kind === "err" ? "err" : "off";
  const label =
    g.kind === "ok"
      ? t("status.allOk")
      : g.kind === "warn"
        ? t("status.warningCount", { count: g.count })
        : g.kind === "err"
          ? t("status.errorCount", { count: g.count })
          : t("status.allOff");
  return <StatusBadge status={status} label={label} />;
}
```

- [ ] **Step 4: Run test**

```bash
npm run test -- src/__tests__/components/global-health-badge.test.tsx
```

Expected: 4 passed.

- [ ] **Step 5: Implement `AppShell.tsx`, `TopBar.tsx`, `SideNav.tsx`**

`AppShell.tsx`:

```tsx
import { Outlet } from "react-router-dom";
import { TopBar } from "./TopBar";
import { SideNav } from "./SideNav";

export function AppShell() {
  return (
    <div className="grid h-screen grid-rows-[56px_1fr] bg-slate-50">
      <TopBar />
      <div className="grid grid-cols-[224px_1fr] overflow-hidden">
        <SideNav />
        <main className="overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
```

`TopBar.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { Bell, RefreshCw, Settings } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { GlobalHealthBadge } from "@/components/status/GlobalHealthBadge";

export function TopBar() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["health"] });
    qc.invalidateQueries({ queryKey: ["snapshot"] });
    qc.invalidateQueries({ queryKey: ["recent-errors"] });
  };

  return (
    <header className="flex h-14 items-center justify-between border-b bg-white px-6">
      <h1 className="text-base font-semibold">{t("app.title")}</h1>
      <div className="flex items-center gap-3">
        <GlobalHealthBadge />
        <Button variant="ghost" size="icon" aria-label={t("actions.refresh")} onClick={refreshAll}>
          <RefreshCw className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" aria-label={t("actions.alerts")}>
          <Bell className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" aria-label={t("actions.settings")}>
          <Settings className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}
```

`SideNav.tsx`:

```tsx
import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useRuntimeSnapshot } from "@/hooks/use-runtime-snapshot";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface Entry {
  key: string;
  to: string;
  enabled: boolean;
}

const entries: Entry[] = [
  { key: "overview", to: "/admin/overview", enabled: true },
  { key: "conversation", to: "/admin/conversation", enabled: true },
  { key: "avatars", to: "/admin/avatars", enabled: false },
  { key: "mcp", to: "/admin/mcp", enabled: false },
  { key: "config", to: "/admin/config", enabled: false },
  { key: "logs", to: "/admin/logs", enabled: false },
];

export function SideNav() {
  const { t } = useTranslation();
  const { data: snap } = useRuntimeSnapshot();
  const olvPort = snap?.ports.find((p) => p.name === "OLV WebSocket / FastAPI");

  return (
    <nav className="flex w-56 flex-col border-r bg-white">
      <ul className="flex-1 p-3 space-y-1">
        <TooltipProvider>
          {entries.map((e) => {
            const link = (
              <NavLink
                to={e.enabled ? e.to : "#"}
                onClick={(ev) => {
                  if (!e.enabled) ev.preventDefault();
                }}
                className={({ isActive }) =>
                  cn(
                    "block rounded px-3 py-2 text-sm",
                    !e.enabled && "cursor-not-allowed text-slate-400",
                    e.enabled && isActive && "bg-slate-100 font-medium",
                    e.enabled && !isActive && "hover:bg-slate-50",
                  )
                }
              >
                {t(`nav.${e.key}`)}
              </NavLink>
            );
            return (
              <li key={e.key}>
                {e.enabled ? (
                  link
                ) : (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div>{link}</div>
                    </TooltipTrigger>
                    <TooltipContent side="right">{t("nav.comingSoon")}</TooltipContent>
                  </Tooltip>
                )}
              </li>
            );
          })}
        </TooltipProvider>
      </ul>
      <div className="border-t p-3 text-xs text-slate-500 space-y-1">
        <div>v{__APP_VERSION__ ?? "0.1.0"}</div>
        <div>{olvPort?.bound_host ?? "127.0.0.1"}</div>
        <div>WS :{olvPort?.port ?? 12393}</div>
        <div>MCP :N/A</div>
      </div>
    </nav>
  );
}
```

Add to `vite.config.ts`'s `define`:

```ts
  define: { __APP_VERSION__: JSON.stringify("0.1.0") },
```

(Place inside the `defineConfig` object; if a `define` already exists, merge.)

- [ ] **Step 6: typecheck**

```bash
npm run typecheck
```

Expected: clean (note: `__APP_VERSION__` may need `declare const __APP_VERSION__: string;` in a `src/global.d.ts`).

- [ ] **Step 7: Add `src/global.d.ts`**

```ts
declare const __APP_VERSION__: string | undefined;
```

- [ ] **Step 8: Commit**

```bash
npm run typecheck && npm run lint
git add admin-frontend/src/components/status admin-frontend/src/components/shell admin-frontend/src/__tests__/components admin-frontend/src/global.d.ts admin-frontend/vite.config.ts
git commit -m "feat(admin-frontend): add AppShell, TopBar, SideNav, GlobalHealthBadge"
```

---

## Task 17: Router + App wiring + WS connect bootstrap

**Files:**
- Modify: `admin-frontend/src/App.tsx`
- Modify: `admin-frontend/src/main.tsx`
- Create: `admin-frontend/src/routes.tsx`
- Create: `admin-frontend/src/pages/OverviewPage.tsx` (stub)
- Create: `admin-frontend/src/pages/ConversationPage.tsx` (stub)
- Create: `admin-frontend/src/pages/NotFoundPage.tsx`

- [ ] **Step 1: `pages/NotFoundPage.tsx`**

```tsx
export default function NotFoundPage() {
  return <div className="p-8 text-slate-500">Not found</div>;
}
```

- [ ] **Step 2: stub `pages/OverviewPage.tsx`**

```tsx
import { useTranslation } from "react-i18next";

export default function OverviewPage() {
  const { t } = useTranslation("overview");
  return <h2 className="text-xl font-semibold">{t("title")}</h2>;
}
```

- [ ] **Step 3: stub `pages/ConversationPage.tsx`**

```tsx
import { useTranslation } from "react-i18next";

export default function ConversationPage() {
  const { t } = useTranslation("conversation");
  return <h2 className="text-xl font-semibold">{t("title")}</h2>;
}
```

- [ ] **Step 4: `src/routes.tsx`**

```tsx
import { Navigate, RouteObject } from "react-router-dom";
import { AppShell } from "@/components/shell/AppShell";
import OverviewPage from "@/pages/OverviewPage";
import ConversationPage from "@/pages/ConversationPage";
import NotFoundPage from "@/pages/NotFoundPage";

export const routes: RouteObject[] = [
  {
    path: "/admin",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="overview" replace /> },
      { path: "overview", element: <OverviewPage /> },
      { path: "conversation", element: <ConversationPage /> },
      { path: "conversation/:sessionId", element: <ConversationPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
  { path: "/", element: <Navigate to="/admin/overview" replace /> },
  { path: "*", element: <NotFoundPage /> },
];
```

- [ ] **Step 5: `src/App.tsx`**

```tsx
import { useEffect, useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createBrowserRouter } from "react-router-dom";
import { routes } from "./routes";
import { OlvWsClient } from "@/lib/ws-client";
import { useConnectionStore } from "@/stores/connection-store";
import "./i18n";

const WS_URL =
  (typeof window !== "undefined" ? window.location.protocol.replace("http", "ws") : "ws:") +
  "//" +
  (typeof window !== "undefined" ? window.location.host : "127.0.0.1:12393") +
  "/client-ws";

export default function App() {
  const queryClient = useMemo(() => new QueryClient(), []);
  const router = useMemo(() => createBrowserRouter(routes), []);
  const setStatus = useConnectionStore((s) => s.setStatus);

  useEffect(() => {
    setStatus("connecting");
    const client = new OlvWsClient(WS_URL);
    client.connect();
    return () => client.close();
  }, [setStatus]);

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
```

- [ ] **Step 6: Run + smoke**

```bash
npm run typecheck
npm run lint
npm run build
```

Expected: clean. Then in another terminal:

```bash
uv run run_server.py &
SERVER=$!
sleep 4
cd admin-frontend && npm run dev &
DEV=$!
sleep 4
# Open http://127.0.0.1:5173 in browser, verify /admin/overview renders title.
kill $DEV $SERVER
```

- [ ] **Step 7: Commit**

```bash
git add admin-frontend/src/App.tsx admin-frontend/src/main.tsx admin-frontend/src/routes.tsx admin-frontend/src/pages
git commit -m "feat(admin-frontend): wire router, react-query, WS bootstrap"
```

---

## Task 18: HealthCard component + Overview row 1

**Files:**
- Create: `admin-frontend/src/components/status/HealthCard.tsx`
- Modify: `admin-frontend/src/pages/OverviewPage.tsx`

- [ ] **Step 1: `HealthCard.tsx`**

```tsx
import { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge, type StatusKind } from "./StatusBadge";
import { cn } from "@/lib/utils";

export interface MetaRow {
  label: string;
  value: ReactNode;
}

export interface HealthCardProps {
  title: string;
  status: StatusKind;
  subStatus: string;
  metaRows?: MetaRow[];
  actionLabel?: string;
  onAction?: () => void;
  actionDisabled?: boolean;
  actionTooltip?: string;
  updatedAt?: string;
  isLoading?: boolean;
}

export function HealthCard(props: HealthCardProps) {
  const dimmed = props.status === "off";
  return (
    <Card className={cn(dimmed && "opacity-60")}>
      <CardHeader className="flex flex-row items-start justify-between gap-2 pb-3">
        <div>
          <CardTitle className="text-sm font-medium text-slate-700">{props.title}</CardTitle>
          <div className="mt-2">
            {props.isLoading ? (
              <Skeleton className="h-5 w-24" />
            ) : (
              <StatusBadge status={props.status} label={props.subStatus} />
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {props.isLoading ? (
          <Skeleton className="h-12 w-full" />
        ) : (
          <dl className="space-y-1 text-xs text-slate-500">
            {(props.metaRows ?? []).map((r) => (
              <div key={r.label} className="flex items-center justify-between">
                <dt>{r.label}</dt>
                <dd className="font-medium text-slate-700">{r.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {props.actionLabel && (
          <div className="mt-4">
            <Button
              variant="secondary"
              size="sm"
              onClick={props.onAction}
              disabled={props.actionDisabled || dimmed}
              title={props.actionTooltip}
            >
              {props.actionLabel}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Add toast surface**

```bash
cd admin-frontend && npx --yes shadcn@latest add sonner
```

In `App.tsx`, render `<Toaster richColors position="top-right" />` (from `sonner` re-export) inside the QueryClientProvider.

- [ ] **Step 3: Build Overview row 1 in `OverviewPage.tsx`**

```tsx
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useHealth } from "@/hooks/use-health";
import { useRuntimeSnapshot } from "@/hooks/use-runtime-snapshot";
import { HealthCard, type MetaRow } from "@/components/status/HealthCard";
import type { HealthResponse, SnapshotResponse } from "@/lib/api-client";

const cardKeys = ["olv", "asr", "tts", "mcp", "ue", "platform"] as const;
type CardKey = (typeof cardKeys)[number];

function rowsFor(
  key: CardKey,
  health: HealthResponse | undefined,
  snap: SnapshotResponse | undefined,
  t: (k: string) => string,
): MetaRow[] {
  if (!health || !snap) return [];
  switch (key) {
    case "olv": {
      const olvPort = snap.ports.find((p) => p.name === "OLV WebSocket / FastAPI");
      return [
        { label: t("ports.port") || "Port", value: olvPort?.port ?? "—" },
        { label: t("ports.boundHost") || "Bound", value: olvPort?.bound_host ?? "—" },
        { label: "Uptime", value: `${health.uptime_s}s` },
      ];
    }
    case "asr":
      return [{ label: "Provider", value: snap.config.asr_provider ?? "—" }];
    case "tts":
      return [{ label: "Provider", value: snap.config.tts_provider ?? "—" }];
    case "mcp":
      return [
        { label: "Online", value: health.components.mcp.online_servers ?? 0 },
        { label: "Total", value: health.components.mcp.total_servers ?? 0 },
      ];
    case "ue":
      return [{ label: "Detail", value: health.components.ue.detail ?? "—" }];
    case "platform":
      return [{ label: "Detail", value: health.components.platform.detail ?? "—" }];
  }
}

export default function OverviewPage() {
  const { t } = useTranslation(["overview", "common"]);
  const { data: health, isLoading: healthLoading } = useHealth();
  const { data: snap, isLoading: snapLoading } = useRuntimeSnapshot();

  const isLoading = healthLoading || snapLoading;
  const comingSoon = t("common:fallback.comingSoon");

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">{t("title")}</h2>
        <p className="text-sm text-slate-500">{t("subtitle")}</p>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {cardKeys.map((key) => {
          const comp = health?.components[key];
          const subLabel = comp?.status ? t(`common:status.${comp.status}`) : "...";
          const actionLabel =
            key === "olv"
              ? "测试连接"
              : key === "mcp"
                ? "前往 MCP 工具页"
                : "测试";
          return (
            <HealthCard
              key={key}
              title={t(`cards.${key}`)}
              status={comp?.status ?? "off"}
              subStatus={subLabel}
              metaRows={rowsFor(key, health, snap, t)}
              actionLabel={actionLabel}
              actionDisabled={key === "mcp"}
              actionTooltip={key === "mcp" ? t("common:nav.comingSoon") : undefined}
              onAction={() => toast.message(comingSoon)}
              isLoading={isLoading}
            />
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: typecheck + run dev to eyeball**

```bash
npm run typecheck
npm run dev
# In another terminal: uv run run_server.py
# Visit http://127.0.0.1:5173/admin/overview ; expect 6 cards.
```

- [ ] **Step 5: Commit**

```bash
git add admin-frontend/src/components/status/HealthCard.tsx admin-frontend/src/pages/OverviewPage.tsx admin-frontend/src/App.tsx admin-frontend/src/components/ui/sonner.tsx admin-frontend/package.json admin-frontend/package-lock.json
git commit -m "feat(admin-frontend): overview health card grid"
```

---

## Task 19: Overview row 2 (port table) + row 3 (recent errors + quick test)

**Files:**
- Modify: `admin-frontend/src/pages/OverviewPage.tsx`

- [ ] **Step 1: Extend `OverviewPage.tsx` after the health grid**

Append a section that consumes `snap.ports`:

```tsx
{/* Row 2: port status table */}
<section className="rounded-md border bg-white">
  <h3 className="border-b px-4 py-3 text-sm font-medium">{t("ports.title")}</h3>
  <table className="w-full text-sm">
    <thead className="text-left text-xs text-slate-500">
      <tr>
        <th className="px-4 py-2">{t("ports.name")}</th>
        <th className="px-4 py-2">{t("ports.port")}</th>
        <th className="px-4 py-2">{t("ports.boundHost")}</th>
        <th className="px-4 py-2">{t("ports.status")}</th>
      </tr>
    </thead>
    <tbody>
      {(snap?.ports ?? []).map((p) => (
        <tr key={p.name} className="border-t min-h-11">
          <td className="px-4 py-3">{p.name}</td>
          <td className="px-4 py-3">{p.port}</td>
          <td className="px-4 py-3">{p.bound_host ?? "—"}</td>
          <td className="px-4 py-3">
            <StatusBadge status={p.status} label={t(`common:status.${p.status}`)} />
          </td>
        </tr>
      ))}
    </tbody>
  </table>
</section>
```

Import `StatusBadge` from `@/components/status/StatusBadge`.

- [ ] **Step 2: Row 3 — recent errors + quick test**

Add `useRecentErrors` hook usage and render. Append:

```tsx
{/* Row 3: recent errors + quick test */}
<section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
  <div className="lg:col-span-2 rounded-md border bg-white">
    <h3 className="border-b px-4 py-3 text-sm font-medium">{t("errors.title")}</h3>
    {recentErrors?.errors.length ? (
      <ul className="divide-y text-sm">
        {recentErrors.errors.slice(-10).reverse().map((e, idx) => (
          <li key={`${e.ts}-${idx}`} className="grid grid-cols-[140px_120px_80px_1fr] gap-2 px-4 py-2">
            <span className="text-xs text-slate-500">{e.ts}</span>
            <span>{e.module || "—"}</span>
            <StatusBadge
              status={e.level === "ERROR" ? "err" : "warn"}
              label={e.level}
            />
            <span className="truncate">{e.message}</span>
          </li>
        ))}
      </ul>
    ) : (
      <p className="px-4 py-6 text-sm text-slate-500">{t("errors.empty")}</p>
    )}
  </div>
  <div className="rounded-md border bg-white p-4">
    <h3 className="text-sm font-medium">{t("quickTest.title")}</h3>
    <div className="mt-3 grid gap-2">
      <Button onClick={() => navigate("/admin/conversation?prefill=hello")}>
        {t("quickTest.text")}
      </Button>
      <Button variant="secondary" onClick={() => toast.message(comingSoon)}>
        {t("quickTest.voice")}
      </Button>
      <Button variant="secondary" onClick={() => toast.message(comingSoon)}>
        {t("quickTest.tts")}
      </Button>
      <Button variant="secondary" onClick={() => toast.message(comingSoon)}>
        {t("quickTest.mcp")}
      </Button>
      <Button variant="secondary" onClick={() => toast.message(comingSoon)}>
        {t("quickTest.ue")}
      </Button>
    </div>
  </div>
</section>
```

Add at the top of the component:

```tsx
const navigate = useNavigate();
const { data: recentErrors } = useRecentErrors();
```

Imports to add at the file head:

```tsx
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useRecentErrors } from "@/hooks/use-recent-errors";
import { StatusBadge } from "@/components/status/StatusBadge";
```

- [ ] **Step 3: typecheck + eyeball**

```bash
npm run typecheck
# Run dev + run_server.py and verify port table + recent errors panel.
```

- [ ] **Step 4: Commit**

```bash
git add admin-frontend/src/pages/OverviewPage.tsx
git commit -m "feat(admin-frontend): overview port table + recent errors + quick test"
```

---

## Task 20: AudioQueueController (TDD)

**Files:**
- Create: `admin-frontend/src/components/avatar/audio-queue-controller.ts`
- Create: `admin-frontend/src/__tests__/avatar/audio-queue-controller.test.ts`

- [ ] **Step 1: Failing test**

```ts
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const { AudioQueueController } = await import("@/components/avatar/audio-queue-controller");

class FakeBufferSource {
  static instances: FakeBufferSource[] = [];
  buffer: unknown = null;
  onended: (() => void) | null = null;
  connectedTo: unknown = null;
  started = false;
  stopped = false;
  constructor() {
    FakeBufferSource.instances.push(this);
  }
  connect(node: unknown) {
    this.connectedTo = node;
  }
  start() {
    this.started = true;
  }
  stop() {
    this.stopped = true;
    this.onended?.();
  }
}

class FakeGainNode {
  gain = { value: 1 };
  connect = vi.fn();
}
class FakeAnalyser {
  fftSize = 256;
  connect = vi.fn();
}

class FakeAudioContext {
  state = "running" as "running" | "suspended" | "closed";
  destination = {};
  createBufferSource = vi.fn(() => new FakeBufferSource());
  createGain = vi.fn(() => new FakeGainNode());
  createAnalyser = vi.fn(() => new FakeAnalyser());
  decodeAudioData = vi.fn(async () => ({ duration: 0.5 }));
  resume = vi.fn(async () => {
    this.state = "running";
  });
}

beforeEach(() => {
  FakeBufferSource.instances = [];
  vi.stubGlobal("AudioContext", FakeAudioContext);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

const tinyWavB64 =
  "UklGRiwAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQgAAACAgICAgICAgA==";

describe("AudioQueueController", () => {
  test("enqueue plays in order", async () => {
    const c = new AudioQueueController();
    c.enqueue(tinyWavB64, { sliceId: "a", messageId: "m" });
    c.enqueue(tinyWavB64, { sliceId: "b", messageId: "m" });
    await vi.waitFor(() => expect(FakeBufferSource.instances.length).toBe(1));
    FakeBufferSource.instances[0].stop();
    await vi.waitFor(() => expect(FakeBufferSource.instances.length).toBe(2));
  });

  test("clear stops current and empties queue", async () => {
    const c = new AudioQueueController();
    c.enqueue(tinyWavB64, { sliceId: "a", messageId: "m" });
    c.enqueue(tinyWavB64, { sliceId: "b", messageId: "m" });
    await vi.waitFor(() => expect(FakeBufferSource.instances.length).toBe(1));
    const cleared = vi.fn();
    c.on("cleared", cleared);
    c.clear();
    expect(FakeBufferSource.instances[0].stopped).toBe(true);
    expect(cleared).toHaveBeenCalled();
    // No new source spawned after clear
    expect(FakeBufferSource.instances.length).toBe(1);
  });

  test("gain mutates volume", () => {
    const c = new AudioQueueController();
    c.setGain(0.5);
    expect(c.getGain()).toBe(0.5);
  });
});
```

- [ ] **Step 2: Implement `audio-queue-controller.ts`**

```ts
type Listener = () => void;

export interface SliceMeta {
  sliceId: string;
  messageId: string;
}

export interface SliceState extends SliceMeta {
  duration: number;
}

type EventName = "start" | "end" | "progress" | "cleared";

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr.buffer;
}

export class AudioQueueController {
  private readonly ctx: AudioContext;
  private readonly gainNode: GainNode;
  public readonly volumeNode: AnalyserNode;
  private queue: Array<{ buffer: ArrayBuffer; meta: SliceMeta }> = [];
  private current: { source: AudioBufferSourceNode; meta: SliceMeta } | null = null;
  private listeners = new Map<EventName, Set<Listener>>();

  constructor() {
    this.ctx = new AudioContext();
    this.gainNode = this.ctx.createGain();
    this.volumeNode = this.ctx.createAnalyser();
    this.volumeNode.fftSize = 256;
    this.gainNode.connect(this.volumeNode);
    this.volumeNode.connect(this.ctx.destination);
  }

  enqueue(b64Wav: string, meta: SliceMeta): void {
    this.queue.push({ buffer: base64ToArrayBuffer(b64Wav), meta });
    void this.pump();
  }

  clear(): void {
    this.queue = [];
    if (this.current) {
      try {
        this.current.source.stop();
      } catch {
        // already stopped
      }
      this.current = null;
    }
    this.emit("cleared");
  }

  setGain(value: number): void {
    this.gainNode.gain.value = value;
  }

  getGain(): number {
    return this.gainNode.gain.value;
  }

  on(event: EventName, cb: Listener): () => void {
    let s = this.listeners.get(event);
    if (!s) {
      s = new Set();
      this.listeners.set(event, s);
    }
    s.add(cb);
    return () => s!.delete(cb);
  }

  async resumeContext(): Promise<void> {
    if (this.ctx.state === "suspended") {
      await this.ctx.resume();
    }
  }

  private emit(event: EventName): void {
    this.listeners.get(event)?.forEach((cb) => cb());
  }

  private async pump(): Promise<void> {
    if (this.current || this.queue.length === 0) return;
    const next = this.queue.shift()!;
    const buf = await this.ctx.decodeAudioData(next.buffer);
    const source = this.ctx.createBufferSource();
    source.buffer = buf;
    source.connect(this.gainNode);
    source.onended = () => {
      this.current = null;
      this.emit("end");
      void this.pump();
    };
    this.current = { source, meta: next.meta };
    source.start();
    this.emit("start");
  }
}
```

- [ ] **Step 3: Run tests**

```bash
npm run test -- src/__tests__/avatar/audio-queue-controller.test.ts
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add admin-frontend/src/components/avatar admin-frontend/src/__tests__/avatar
git commit -m "feat(admin-frontend): add AudioQueueController with serial playback"
```

---

## Task 21: BroadcastStateBadge + MessageList + MessageBubble + ProcessDrawer

**Files:**
- Create: `admin-frontend/src/components/conversation/BroadcastStateBadge.tsx`
- Create: `admin-frontend/src/components/conversation/MessageBubble.tsx`
- Create: `admin-frontend/src/components/conversation/MessageList.tsx`
- Create: `admin-frontend/src/components/conversation/ProcessDrawer.tsx`
- Create: `admin-frontend/src/__tests__/conversation/message-list.test.tsx`

- [ ] **Step 1: `BroadcastStateBadge.tsx`**

```tsx
import { useTranslation } from "react-i18next";
import { StatusBadge, type StatusKind } from "@/components/status/StatusBadge";
import type { BroadcastState } from "@/stores/session-store";

const map: Record<BroadcastState, StatusKind> = {
  idle: "off",
  listening: "busy",
  recognizing: "busy",
  thinking: "busy",
  speaking: "busy",
  interrupted: "warn",
  completed: "ok",
  error: "err",
};

export function BroadcastStateBadge({ state }: { state: BroadcastState }) {
  const { t } = useTranslation("conversation");
  return <StatusBadge status={map[state]} label={t(`broadcast.${state}`)} />;
}
```

- [ ] **Step 2: `MessageBubble.tsx`**

```tsx
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Message } from "@/stores/session-store";

export function MessageBubble({
  msg,
  onViewProcess,
}: {
  msg: Message;
  onViewProcess?: (id: string) => void;
}) {
  const { t } = useTranslation("conversation");
  if (msg.kind === "transition") {
    return <div className="text-center text-xs text-slate-400">{msg.text}</div>;
  }
  if (msg.kind === "error") {
    return (
      <div className="rounded border border-status-err/40 bg-status-err/10 px-3 py-2 text-sm text-status-err">
        <span className="font-medium">{msg.code ?? "error"}</span>: {msg.text}
      </div>
    );
  }
  const isUser = msg.kind === "user-text" || msg.kind === "user-voice";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[70%] rounded-md px-3 py-2 text-sm",
          isUser ? "bg-slate-900 text-white" : "border bg-white",
        )}
      >
        <p>{msg.text}</p>
        {msg.kind === "assistant" && (
          <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
            <span>{new Date(msg.ts).toLocaleTimeString()}</span>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onViewProcess?.(msg.id)}
              className="h-6 px-2"
            >
              {t("process.title")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: `MessageList.tsx`**

```tsx
import { useRef, useEffect } from "react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MessageBubble } from "./MessageBubble";
import type { Message } from "@/stores/session-store";

export function MessageList({
  messages,
  onViewProcess,
}: {
  messages: Message[];
  onViewProcess?: (id: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight });
  }, [messages]);

  return (
    <ScrollArea className="flex-1">
      <div ref={ref} className="space-y-3 px-4 py-3">
        {messages.map((m) => (
          <MessageBubble key={m.id} msg={m} onViewProcess={onViewProcess} />
        ))}
      </div>
    </ScrollArea>
  );
}
```

- [ ] **Step 4: `ProcessDrawer.tsx`**

```tsx
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useTranslation } from "react-i18next";

export function ProcessDrawer({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const { t } = useTranslation("conversation");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[420px]">
        <SheetHeader>
          <SheetTitle>{t("process.title")}</SheetTitle>
        </SheetHeader>
        <p className="mt-4 text-sm text-slate-500">{t("process.empty")}</p>
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 5: Smoke test for MessageList**

```tsx
// src/__tests__/conversation/message-list.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { I18nextProvider } from "react-i18next";
import i18n from "@/i18n";
import { MessageList } from "@/components/conversation/MessageList";

describe("MessageList", () => {
  test("renders user and assistant bubbles and transitions and errors", () => {
    render(
      <I18nextProvider i18n={i18n}>
        <MessageList
          messages={[
            { kind: "user-text", id: "1", text: "hi", ts: 0 },
            {
              kind: "assistant",
              id: "2",
              text: "hello",
              ts: 0,
              broadcastDone: false,
              audioSegments: [],
            },
            { kind: "transition", id: "3", text: "thinking...", ts: 0 },
            { kind: "error", id: "4", text: "boom", ts: 0, code: "E1" },
          ]}
        />
      </I18nextProvider>,
    );
    expect(screen.getByText("hi")).toBeInTheDocument();
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText("thinking...")).toBeInTheDocument();
    expect(screen.getByText("boom", { exact: false })).toBeInTheDocument();
  });
});
```

- [ ] **Step 6: Run tests + commit**

```bash
npm run test
git add admin-frontend/src/components/conversation admin-frontend/src/__tests__/conversation
git commit -m "feat(admin-frontend): add message list, bubble, broadcast badge, process drawer"
```

---

## Task 22: HistoryPanel + WS history wiring

**Files:**
- Create: `admin-frontend/src/components/conversation/HistoryPanel.tsx`
- Create: `admin-frontend/src/hooks/use-history-list.ts`

- [ ] **Step 1: `hooks/use-history-list.ts`**

```ts
import { useEffect } from "react";
import { useSessionStore, type HistoryItem } from "@/stores/session-store";
import type { OlvWsClient } from "@/lib/ws-client";

export function useHistoryList(client: OlvWsClient | null) {
  const setHistoryList = useSessionStore((s) => s.setHistoryList);

  useEffect(() => {
    if (!client) return;
    client.send({ type: "fetch-history-list" });
    return client.on("history-list", (msg) => {
      const items: HistoryItem[] = (msg.histories ?? []).map((h) => ({
        uid: h.uid,
        title: h.latest_message ?? "未命名会话",
        summary: h.latest_message ?? "",
        updatedAt: h.timestamp ? Date.parse(h.timestamp) : Date.now(),
        status: "completed",
      }));
      setHistoryList(items);
    });
  }, [client, setHistoryList]);
}
```

- [ ] **Step 2: `components/conversation/HistoryPanel.tsx`**

```tsx
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useSessionStore } from "@/stores/session-store";
import type { OlvWsClient } from "@/lib/ws-client";
import { cn } from "@/lib/utils";

export function HistoryPanel({ client }: { client: OlvWsClient | null }) {
  const { t } = useTranslation("conversation");
  const navigate = useNavigate();
  const { sessionId } = useParams();
  const list = useSessionStore((s) => s.historyList);
  const [q, setQ] = useState("");
  const filtered = list.filter((h) => h.title.toLowerCase().includes(q.toLowerCase()));

  const onNew = () => {
    client?.send({ type: "create-new-history" });
  };

  return (
    <aside className="flex h-full w-72 flex-col border-r bg-white">
      <div className="space-y-2 p-3">
        <Input
          placeholder={t("history.search")}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Button className="w-full" onClick={onNew}>
          {t("composer.send") /* placeholder until new-session string finalized */}
        </Button>
      </div>
      <ScrollArea className="flex-1">
        {filtered.length === 0 ? (
          <p className="px-4 py-6 text-sm text-slate-500">{t("history.empty")}</p>
        ) : (
          <ul>
            {filtered.map((h) => (
              <li key={h.uid}>
                <button
                  type="button"
                  onClick={() => navigate(`/admin/conversation/${h.uid}`)}
                  className={cn(
                    "w-full border-b px-4 py-3 text-left text-sm hover:bg-slate-50",
                    sessionId === h.uid && "border-l-4 border-l-status-busy bg-slate-100",
                  )}
                >
                  <div className="truncate font-medium">{h.title}</div>
                  <div className="truncate text-xs text-slate-500">{h.summary}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
    </aside>
  );
}
```

- [ ] **Step 3: Add a `nav.newSession`-style copy** by reusing `actions.newSession`

Replace the button text `t("composer.send")` with `t("common:actions.newSession")` (you'll need `useTranslation(["conversation", "common"])`).

- [ ] **Step 4: typecheck + commit**

```bash
npm run typecheck
git add admin-frontend/src/components/conversation/HistoryPanel.tsx admin-frontend/src/hooks/use-history-list.ts
git commit -m "feat(admin-frontend): add HistoryPanel and history-list WS hook"
```

---

## Task 23: ConversationPanel + Composer + WS message wiring

**Files:**
- Create: `admin-frontend/src/components/conversation/ConversationPanel.tsx`
- Create: `admin-frontend/src/components/conversation/Composer.tsx`
- Create: `admin-frontend/src/hooks/use-conversation-ws.ts`
- Modify: `admin-frontend/src/pages/ConversationPage.tsx`

- [ ] **Step 1: `hooks/use-conversation-ws.ts`**

This consolidates all WS-to-store wiring for the conversation page.

```ts
import { useEffect } from "react";
import { useSessionStore } from "@/stores/session-store";
import type { OlvWsClient } from "@/lib/ws-client";
import type { AudioQueueController } from "@/components/avatar/audio-queue-controller";

let assistantIdCounter = 0;

export function useConversationWs(client: OlvWsClient | null, audio: AudioQueueController | null) {
  const appendMessage = useSessionStore((s) => s.appendMessage);
  const setBroadcastState = useSessionStore((s) => s.setBroadcastState);
  const markInterrupted = useSessionStore((s) => s.markCurrentAssistantInterrupted);
  const setSession = useSessionStore((s) => s.setSession);
  const clearMessages = useSessionStore((s) => s.clearMessages);

  useEffect(() => {
    if (!client) return;
    const offFull = client.on("full-text", (msg) => {
      const id = `m-${++assistantIdCounter}`;
      const role = (msg as { role?: string }).role;
      if (role === "user") {
        appendMessage({ kind: "user-text", id, text: msg.text, ts: Date.now() });
      } else {
        appendMessage({
          kind: "assistant",
          id,
          text: msg.text,
          ts: Date.now(),
          broadcastDone: false,
          audioSegments: [],
        });
      }
    });

    const offTrans = client.on("user-input-transcription", (msg) => {
      appendMessage({
        kind: "user-voice",
        id: `u-${++assistantIdCounter}`,
        text: msg.text,
        ts: Date.now(),
      });
    });

    const offAudio = client.on("audio", (msg) => {
      if (msg.audio && audio) {
        audio.enqueue(msg.audio, { sliceId: `s-${assistantIdCounter}`, messageId: `m-${assistantIdCounter}` });
      }
    });

    const offPlay = client.on("audio-play-start", () => setBroadcastState("speaking"));

    const offControl = client.on("control", (msg) => {
      switch (msg.text) {
        case "conversation-chain-start":
          setBroadcastState("thinking");
          break;
        case "conversation-chain-end":
          setBroadcastState("completed");
          window.setTimeout(() => setBroadcastState("idle"), 2000);
          break;
        case "interrupt":
          audio?.clear();
          setBroadcastState("interrupted");
          markInterrupted();
          window.setTimeout(() => setBroadcastState("idle"), 2000);
          break;
        case "start-mic":
          setBroadcastState("listening");
          break;
        case "mic-audio-end":
          setBroadcastState("recognizing");
          break;
      }
    });

    const offNew = client.on("new-history-created", (msg) => {
      setSession(msg.history_uid);
      clearMessages();
    });

    const offHistory = client.on("history-data", (msg) => {
      clearMessages();
      msg.messages.forEach((m, i) => {
        if (m.role === "user") {
          appendMessage({
            kind: "user-text",
            id: `h-${i}`,
            text: m.content,
            ts: Date.now() - (msg.messages.length - i) * 1000,
          });
        } else {
          appendMessage({
            kind: "assistant",
            id: `h-${i}`,
            text: m.content,
            ts: Date.now() - (msg.messages.length - i) * 1000,
            broadcastDone: true,
            audioSegments: [],
          });
        }
      });
    });

    const offError = client.on("error", (msg) => {
      appendMessage({ kind: "error", id: `e-${Date.now()}`, text: msg.message, ts: Date.now(), code: msg.code });
      setBroadcastState("error");
    });

    return () => {
      offFull();
      offTrans();
      offAudio();
      offPlay();
      offControl();
      offNew();
      offHistory();
      offError();
    };
  }, [client, audio, appendMessage, setBroadcastState, markInterrupted, setSession, clearMessages]);
}
```

- [ ] **Step 2: `Composer.tsx`**

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Mic, Send, Square } from "lucide-react";
import { useSessionStore } from "@/stores/session-store";
import type { OlvWsClient } from "@/lib/ws-client";
import type { AudioQueueController } from "@/components/avatar/audio-queue-controller";

interface Props {
  client: OlvWsClient | null;
  audio: AudioQueueController | null;
  initialText?: string;
  onMicStart?: () => Promise<void> | void;
  onMicStop?: () => Promise<void> | void;
  isRecording: boolean;
}

export function Composer({ client, audio, initialText, onMicStart, onMicStop, isRecording }: Props) {
  const { t } = useTranslation("conversation");
  const [text, setText] = useState(initialText ?? "");
  const broadcastState = useSessionStore((s) => s.broadcastState);
  const sendDisabled = !text.trim() || broadcastState === "thinking" || broadcastState === "speaking";

  const handleSend = async () => {
    if (!client || sendDisabled) return;
    await audio?.resumeContext();
    client.send({ type: "text-input", text: text.trim() });
    setText("");
  };

  const handleInterrupt = () => {
    audio?.clear();
    client?.send({ type: "interrupt-signal" });
  };

  return (
    <div className="flex items-end gap-2 border-t bg-white p-3">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("composer.placeholder")}
        maxLength={1000}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void handleSend();
          }
        }}
        className="min-h-11 flex-1"
      />
      <Button
        type="button"
        variant={isRecording ? "destructive" : "secondary"}
        onClick={() => (isRecording ? onMicStop?.() : onMicStart?.())}
        aria-label="microphone"
      >
        <Mic className="h-4 w-4" />
      </Button>
      <Button type="button" onClick={handleSend} disabled={sendDisabled} aria-label="send">
        <Send className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="destructive"
        onClick={handleInterrupt}
        disabled={broadcastState !== "speaking"}
      >
        <Square className="h-4 w-4" />
      </Button>
    </div>
  );
}
```

- [ ] **Step 3: `ConversationPanel.tsx`**

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSessionStore } from "@/stores/session-store";
import { MessageList } from "./MessageList";
import { BroadcastStateBadge } from "./BroadcastStateBadge";
import { ProcessDrawer } from "./ProcessDrawer";

export function ConversationPanel({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation("conversation");
  const messages = useSessionStore((s) => s.messages);
  const broadcastState = useSessionStore((s) => s.broadcastState);
  const [processOpen, setProcessOpen] = useState(false);

  return (
    <section className="flex h-full flex-col bg-slate-50">
      <header className="flex h-14 items-center justify-between border-b bg-white px-4">
        <h2 className="text-sm font-medium">
          {t("session.untitled")} · {t("session.messages", { count: messages.length })}
        </h2>
        <BroadcastStateBadge state={broadcastState} />
      </header>
      <MessageList messages={messages} onViewProcess={() => setProcessOpen(true)} />
      {children}
      <ProcessDrawer open={processOpen} onOpenChange={setProcessOpen} />
    </section>
  );
}
```

- [ ] **Step 4: Wire the page together — `pages/ConversationPage.tsx`**

```tsx
import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { HistoryPanel } from "@/components/conversation/HistoryPanel";
import { ConversationPanel } from "@/components/conversation/ConversationPanel";
import { Composer } from "@/components/conversation/Composer";
import { StagePanel } from "@/components/avatar/StagePanel";
import { OlvWsClient } from "@/lib/ws-client";
import { AudioQueueController } from "@/components/avatar/audio-queue-controller";
import { useHistoryList } from "@/hooks/use-history-list";
import { useConversationWs } from "@/hooks/use-conversation-ws";

const WS_URL = (() => {
  const proto = window.location.protocol.replace("http", "ws");
  return `${proto}//${window.location.host}/client-ws`;
})();

export default function ConversationPage() {
  const { sessionId } = useParams();
  const [params] = useSearchParams();
  const prefill = params.get("prefill") ?? undefined;
  const [client, setClient] = useState<OlvWsClient | null>(null);
  const audio = useMemo(() => new AudioQueueController(), []);

  useEffect(() => {
    const c = new OlvWsClient(WS_URL);
    c.connect();
    setClient(c);
    return () => c.close();
  }, []);

  useHistoryList(client);
  useConversationWs(client, audio);

  useEffect(() => {
    if (client && sessionId) {
      client.send({ type: "fetch-history", history_uid: sessionId });
    }
  }, [client, sessionId]);

  return (
    <div className="grid h-[calc(100vh-3.5rem)] grid-cols-[280px_1fr_360px]">
      <HistoryPanel client={client} />
      <ConversationPanel>
        <Composer client={client} audio={audio} initialText={prefill} isRecording={false} />
      </ConversationPanel>
      <StagePanel audio={audio} client={client} />
    </div>
  );
}
```

- [ ] **Step 5: typecheck + lint**

```bash
npm run typecheck
npm run lint
```

(StagePanel doesn't exist yet — type errors expected. Proceed to the next task to add it; do **not** commit yet.)

- [ ] **Step 6: Commit blocker note**

Skip commit at this task; commit at end of Task 24.

---

## Task 24: StagePanel + Live2DStage (lazy)

**Files:**
- Create: `admin-frontend/src/components/avatar/StagePanel.tsx`
- Create: `admin-frontend/src/components/avatar/Live2DStage.tsx`

- [ ] **Step 1: `StagePanel.tsx`**

```tsx
import { Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { useSettingsStore } from "@/stores/settings-store";
import type { OlvWsClient } from "@/lib/ws-client";
import type { AudioQueueController } from "./audio-queue-controller";

const Live2DStage = lazy(() => import("./Live2DStage"));

export function StagePanel({
  audio,
  client,
}: {
  audio: AudioQueueController;
  client: OlvWsClient | null;
}) {
  const { t } = useTranslation("conversation");
  const enabled = useSettingsStore((s) => s.live2dPreviewEnabled);
  const setEnabled = useSettingsStore((s) => s.setLive2dPreviewEnabled);

  return (
    <aside className="flex h-full w-90 flex-col gap-4 border-l bg-white p-3">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <CardTitle className="text-sm">Live2D</CardTitle>
          <Button size="sm" variant="ghost" onClick={() => setEnabled(!enabled)}>
            {enabled ? t("common:actions.collapse") : t("common:actions.expand")}
          </Button>
        </CardHeader>
        <CardContent>
          {enabled ? (
            <Suspense fallback={<div className="h-64" />}>
              <Live2DStage audio={audio} client={client} />
            </Suspense>
          ) : (
            <p className="text-xs text-slate-500">
              {t("stage.live2dCollapsed", { action: t("common:actions.expand") })}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">{t("stage.volume")}</CardTitle>
        </CardHeader>
        <CardContent>
          <Slider
            defaultValue={[100]}
            max={100}
            step={1}
            onValueChange={(v) => audio.setGain((v[0] ?? 100) / 100)}
          />
        </CardContent>
      </Card>
    </aside>
  );
}
```

- [ ] **Step 2: Add `slider` shadcn component**

```bash
cd admin-frontend && npx --yes shadcn@latest add slider
```

- [ ] **Step 3: `Live2DStage.tsx` (minimal viable)**

```tsx
import { useEffect, useRef } from "react";
import { Application } from "pixi.js";
import { Live2DModel } from "pixi-live2d-display";
import type { AudioQueueController } from "./audio-queue-controller";
import type { OlvWsClient } from "@/lib/ws-client";

export default function Live2DStage({
  audio,
  client,
}: {
  audio: AudioQueueController;
  client: OlvWsClient | null;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const modelRef = useRef<Live2DModel | null>(null);

  useEffect(() => {
    if (!ref.current || !client) return;
    const app = new Application({ view: ref.current, transparent: true, autoStart: true });

    let cancelled = false;
    const off = client.on("set-model-and-conf", async (msg) => {
      const url = (msg as unknown as { model_info?: { url?: string } }).model_info?.url;
      if (!url) return;
      const model = await Live2DModel.from(url);
      if (cancelled) return;
      modelRef.current = model;
      app.stage.addChild(model as unknown as never);
    });

    // Lip-sync RAF loop reads volumeNode
    const data = new Uint8Array(audio.volumeNode.frequencyBinCount);
    const tick = () => {
      audio.volumeNode.getByteFrequencyData(data);
      const avg = data.reduce((a, b) => a + b, 0) / data.length / 255;
      const model = modelRef.current;
      if (model) {
        // safe-cast around the internal API
        const core = (model as unknown as { internalModel?: { coreModel?: { setParameterValueById?: (id: string, v: number) => void } } })
          .internalModel?.coreModel;
        core?.setParameterValueById?.("ParamMouthOpenY", avg);
      }
      raf = requestAnimationFrame(tick);
    };
    let raf = requestAnimationFrame(tick);

    return () => {
      cancelled = true;
      off();
      cancelAnimationFrame(raf);
      app.destroy(true);
    };
  }, [audio, client]);

  return <canvas ref={ref} className="h-64 w-full bg-slate-100" />;
}
```

- [ ] **Step 4: Build + manual smoke**

```bash
npm run typecheck
npm run build
```

Run dev server alongside `uv run run_server.py`; visit `/admin/conversation`; send a text question; observe:
- assistant message appears
- audio plays
- expanding Live2D loads model and mouth animates

If Live2D fails to load, the rest of the page still works — that's the spec contract.

- [ ] **Step 5: Commit (Task 23+24 together)**

```bash
git add admin-frontend/src/hooks/use-conversation-ws.ts admin-frontend/src/components/conversation/ConversationPanel.tsx admin-frontend/src/components/conversation/Composer.tsx admin-frontend/src/components/avatar/StagePanel.tsx admin-frontend/src/components/avatar/Live2DStage.tsx admin-frontend/src/pages/ConversationPage.tsx admin-frontend/src/components/ui/slider.tsx
git commit -m "feat(admin-frontend): conversation page with text send, audio, Live2D preview"
```

---

## Task 25: Voice input (MediaRecorder + mic-audio-data)

**Files:**
- Create: `admin-frontend/src/hooks/use-mic-input.ts`
- Modify: `admin-frontend/src/pages/ConversationPage.tsx`

- [ ] **Step 1: `use-mic-input.ts`**

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import type { OlvWsClient } from "@/lib/ws-client";

const SAMPLE_RATE = 16000;
const SLICE_MS = 200;

export function useMicInput(client: OlvWsClient | null) {
  const [isRecording, setIsRecording] = useState(false);
  const ctxRef = useRef<AudioContext | null>(null);
  const procRef = useRef<ScriptProcessorNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const start = useCallback(async () => {
    if (!client || isRecording) return;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    ctxRef.current = ctx;
    const source = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(2048, 1, 1);
    procRef.current = proc;

    const buffer: number[] = [];
    const sliceSamples = (SAMPLE_RATE * SLICE_MS) / 1000;
    proc.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      for (let i = 0; i < input.length; i++) buffer.push(input[i]);
      while (buffer.length >= sliceSamples) {
        const chunk = buffer.splice(0, sliceSamples);
        client.send({ type: "mic-audio-data", audio: chunk });
      }
    };
    source.connect(proc);
    proc.connect(ctx.destination);
    setIsRecording(true);
  }, [client, isRecording]);

  const stop = useCallback(() => {
    procRef.current?.disconnect();
    procRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    ctxRef.current?.close();
    ctxRef.current = null;
    setIsRecording(false);
    client?.send({ type: "mic-audio-end" });
  }, [client]);

  useEffect(() => stop, [stop]);

  return { isRecording, start, stop };
}
```

- [ ] **Step 2: Update `ConversationPage.tsx` to use it**

Replace the `<Composer … isRecording={false} />` block with:

```tsx
const mic = useMicInput(client);
// …
<Composer
  client={client}
  audio={audio}
  initialText={prefill}
  isRecording={mic.isRecording}
  onMicStart={mic.start}
  onMicStop={mic.stop}
/>
```

Import: `import { useMicInput } from "@/hooks/use-mic-input";`.

- [ ] **Step 3: typecheck + commit**

```bash
npm run typecheck
git add admin-frontend/src/hooks/use-mic-input.ts admin-frontend/src/pages/ConversationPage.tsx
git commit -m "feat(admin-frontend): add voice input via MediaRecorder → mic-audio-data"
```

---

## Task 26: docs/admin-frontend.md

**Files:**
- Create: `docs/admin-frontend.md`

- [ ] **Step 1: Write the docs**

```markdown
# Admin Frontend

The operations console for Open-LLM-VTuber. Lives at `admin-frontend/`, an independent npm workspace.

## Quick Start

Dev:

```bash
uv run run_server.py             # starts OLV on :12393
cd admin-frontend
npm install
npm run dev                      # http://127.0.0.1:5173
```

Prod:

```bash
cd admin-frontend
npm run build                    # outputs admin-frontend/dist/
# Restart OLV; it auto-mounts /admin → admin-frontend/dist
# Visit http://<host>:12393/admin/
```

## Architecture

- React 18 + TypeScript strict
- Vite 5 (dev server on :5173 with proxy to OLV)
- Tailwind CSS + shadcn/ui (New York / neutral)
- TanStack Query v5 + Zustand 4
- Live2D via pixi.js + pixi-live2d-display
- WebSocket against OLV's existing `/client-ws` (shared protocol with the runtime frontend and UE client)
- Three GET endpoints on OLV: `/api/health`, `/api/runtime/snapshot`, `/api/runtime/recent-errors`

## API Contract

### `GET /api/health`
Returns service health snapshot with `status: ok|degraded|error` and a `components` map (`olv|asr|tts|vad|mcp|ue|platform`). MCP / UE / Platform are `off` until the corresponding sub-projects land.

### `GET /api/runtime/snapshot`
Returns `ports[]`, `config` (with `llm_api_key_masked`), and `current_session`.

### `GET /api/runtime/recent-errors`
Returns the in-process loguru warning/error ring buffer (capacity 200).

## WS Protocol Coverage

The admin frontend uses these `/client-ws` message types (unchanged from OLV):
- Inbound: full-text, audio, set-model-and-conf, new-history-created, history-data, history-list, user-input-transcription, control, error
- Outbound: text-input, mic-audio-data, mic-audio-end, interrupt-signal, fetch-history-list, fetch-history, create-new-history, audio-play-start, heartbeat

## Future Pages

Six side-nav entries exist; only Overview and Conversation are implemented in P0. The other four are present as disabled tooltips and will be implemented in follow-up specs:

- 数字人 — paired with the UE WebSocket sub-project
- MCP 工具 — paired with the customer platform adapter
- 配置 — pulls and writes `conf.yaml`
- 日志与调试 — surfaces full MessagePart trace
```

- [ ] **Step 2: Commit**

```bash
git add docs/admin-frontend.md
git commit -m "docs(admin): add admin-frontend overview, API contract, future-page map"
```

---

## Task 27: Manual acceptance run

**Files:**
- None (verification only)

- [ ] **Step 1: Backend test sweep**

```bash
uv run pytest tests -v
uv run ruff check .
```

Expected: all pass.

- [ ] **Step 2: Frontend test sweep**

```bash
cd admin-frontend
npm run typecheck
npm run lint
npm run test
npm run format:check
npm run build
```

Expected: all green; `dist/` produced; bundle gzipped under 800KB total.

- [ ] **Step 3: End-to-end smoke**

```bash
uv run run_server.py &
SERVER=$!
sleep 6
```

Open `http://127.0.0.1:12393/admin/overview` and verify each item in the **Manual Acceptance Checklist** of the spec:

- 6 health cards render within 5s; MCP/UE/Platform show "未启用" gray.
- Port table shows `12393 / 127.0.0.1 / 在线` for OLV.
- Recent errors panel shows entries (provoke one by misconfiguring TTS briefly).
- Quick test → 测试文本问答 navigates to conversation page; composer prefilled.
- New session button creates a new history; switching restores past messages.
- Text send produces user bubble + assistant bubble + audio playback.
- Voice button records → recognition → assistant response.
- Interrupt during speaking stops audio immediately and shows interrupted badge.
- Live2D preview expands and mouth animates with audio.
- `/api/runtime/snapshot` masks `llm_api_key` field.

```bash
kill $SERVER
```

- [ ] **Step 4: Final tidy commit (if anything needed)**

If acceptance surfaced trivial copy fixes or untracked files, commit them now. Otherwise no commit.

---

## Self-Review Notes

The plan covers every spec section:

| Spec section | Plan task(s) |
| --- | --- |
| Backend `admin_routes.py` health / snapshot / recent-errors | 2, 3, 4, 5, 6 |
| Backend `server.py` wiring + static mount + sink | 7 |
| Frontend scaffold (Vite + TS + Tailwind + shadcn + i18n) | 8, 9, 10, 15 |
| WS protocol + client | 11 |
| API client + hooks | 13 |
| Zustand stores | 14 |
| AppShell + TopBar + SideNav + GlobalHealthBadge | 16, 17 |
| Overview page (3 rows) | 18, 19 |
| Conversation page — AudioQueueController | 20 |
| Conversation page — messages / drawer / state | 21 |
| Conversation page — history panel | 22 |
| Conversation page — panel/composer/page wiring + Live2D | 23, 24 |
| Voice input | 25 |
| Docs | 26 |
| Manual acceptance | 27 |
| Mask helper | 3 (backend) + 12 (frontend) |

Type names stay consistent across tasks: `OlvWsClient`, `AudioQueueController`, `BroadcastState`, `HealthCard`, `StatusBadge`, `HistoryItem`, `Message`.

If a step in Task 22 or 23 surfaces a needed string that wasn't added in Task 15, add it to both `zh-CN` and `en-US` files in the same commit — do not skip the English copy.

Spec ↔ plan parity: confirmed.
