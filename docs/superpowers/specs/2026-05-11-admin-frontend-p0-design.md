# Admin Frontend P0 Design

> Scope: independent admin-frontend project covering shell + Overview page + Conversation Console page, per《智慧数字人一体机项目说明书》§9. The remaining four pages (数字人 / MCP / 配置 / 日志) ship in later specs.
>
> This spec supersedes `docs/superpowers/specs/2026-05-09-open-llm-vtuber-frontend-console-design.md` (deprecated; that earlier design redesigned the `frontend/` submodule and is dropped in favor of a separate admin project).

## Scope

P0 in scope:

- New independent npm workspace at `admin-frontend/` (React 18 + TS + Vite + Tailwind + shadcn/ui + TanStack Query + Zustand).
- Minimal backend additions in `src/open_llm_vtuber/`: `admin_routes.py` (three GET endpoints), a loguru memory sink for recent errors, and a `StaticFiles` mount.
- AppShell + routing for six side-nav entries (four placeholder/disabled).
- Overview page with health cards, port table, recent errors, quick test actions.
- Conversation Console page with history sidebar, message stream, composer (text + voice + interrupt), Live2D preview stage, local audio playback.
- Connecting to OLV via the existing `/client-ws` protocol (no new WS endpoint).
- Sensitive value masking on `/api/runtime/snapshot`.
- i18n in zh-CN / en-US.

Out of scope (deferred to later specs):

- 数字人 / MCP 工具 / 配置 / 日志与调试 pages (side-nav disabled placeholders).
- Backend pipeline / MessagePart / three-agent system (spec A).
- Customer platform MCP adapter (spec B).
- UE WebSocket client + avatar profile (spec C).
- Authentication middleware (relies on existing host binding from `conf.yaml`).
- E2E test harness (Playwright). Unit tests only this phase.

## Product Direction

Admin-frontend is the **operations console** for on-site reception staff and administrators, not the public-facing observer screen (UE digital human client owns that). It must:

- Make current state legible at a glance.
- Make conversation ops fast (text, voice, interrupt, new session).
- Optionally preview Live2D and play audio locally for debugging when UE is offline or for verification.
- Keep debug/process detail folded by default.
- Mask sensitive configuration end-to-end.

Visual language: 浅灰工作台 + 白色卡片 + 低饱和蓝绿主色 + 6~8px 圆角 + 触控适配 (≥44px hit targets, no hover-only affordances).

## File Structure

```
open-llm-vtuber/
├── admin-frontend/                 # new independent npm workspace
│   ├── package.json
│   ├── vite.config.ts              # base '/admin/' (prod) / '/' (dev); proxy /api & /client-ws
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── components.json             # shadcn/ui CLI config (New York, neutral)
│   ├── tsconfig.json               # strict
│   ├── index.html
│   ├── README.md
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                 # router + providers
│       ├── routes.tsx
│       ├── lib/
│       │   ├── api-client.ts       # fetch wrapper for /api/*
│       │   ├── ws-client.ts        # OlvWsClient singleton
│       │   ├── ws-protocol.ts      # TS types mirroring websocket_handler.py
│       │   └── mask.ts
│       ├── stores/
│       │   ├── connection-store.ts # zustand
│       │   ├── session-store.ts
│       │   └── settings-store.ts   # persisted via localStorage
│       ├── hooks/
│       │   ├── use-health.ts
│       │   ├── use-runtime-snapshot.ts
│       │   └── use-recent-errors.ts
│       ├── components/
│       │   ├── ui/                 # shadcn-generated
│       │   ├── shell/
│       │   │   ├── AppShell.tsx
│       │   │   ├── TopBar.tsx
│       │   │   ├── SideNav.tsx
│       │   │   └── PageHeader.tsx
│       │   ├── status/
│       │   │   ├── StatusBadge.tsx
│       │   │   ├── HealthCard.tsx
│       │   │   └── GlobalHealthBadge.tsx
│       │   ├── conversation/
│       │   │   ├── HistoryPanel.tsx
│       │   │   ├── ConversationPanel.tsx
│       │   │   ├── MessageList.tsx
│       │   │   ├── MessageBubble.tsx
│       │   │   ├── Composer.tsx
│       │   │   ├── BroadcastStateBadge.tsx
│       │   │   └── ProcessDrawer.tsx
│       │   └── avatar/
│       │       ├── StagePanel.tsx
│       │       ├── Live2DStage.tsx           # React.lazy
│       │       └── audio-queue-controller.ts # plain TS class
│       ├── pages/
│       │   ├── OverviewPage.tsx
│       │   ├── ConversationPage.tsx
│       │   └── NotFoundPage.tsx
│       └── locales/
│           ├── zh-CN/{common,overview,conversation}.json
│           └── en-US/{common,overview,conversation}.json
└── src/open_llm_vtuber/
    ├── server.py                   # +include_router(admin), +mount('/admin', StaticFiles), +install loguru sink
    └── admin_routes.py             # NEW
└── tests/
    └── test_admin_routes.py        # NEW
└── docs/
    └── admin-frontend.md           # NEW: architecture, API contract, WS protocol table, future page map
```

## Architecture

### Communication model

```
admin-frontend (Vite dev :5173 | prod /admin/* on :12393)
  ├─ HTTP REST → OLV FastAPI :12393
  │   GET /api/health              (refetchInterval 5s)
  │   GET /api/runtime/snapshot    (refetchInterval 30s)
  │   GET /api/runtime/recent-errors (refetchInterval 10s)
  └─ WebSocket → OLV /client-ws    (existing protocol, no backend changes)
       Shared with frontend submodule and UE client; each connection gets its own ServiceContext.
```

### Tech stack (locked)

- React 18, TypeScript strict, Vite 5
- Tailwind CSS 3, shadcn/ui (New York / neutral), Radix primitives
- TanStack Query v5, Zustand 4
- react-router-dom v6
- pixi.js v7 + pixi-live2d-display ^0.4 (matches OLV submodule)
- Web Audio API for playback (no library)
- i18next + react-i18next (zh-CN default, en-US secondary)
- vitest + @testing-library/react for unit tests
- ESLint + Prettier; no Husky in P0

### Deployment

- Dev: `cd admin-frontend && npm run dev` → :5173; Vite proxy forwards `/api/*` and `/client-ws` (with `ws: true`) to `http://127.0.0.1:12393`.
- Prod: `npm run build` → `admin-frontend/dist/`. OLV `server.py` mounts it at `/admin`. Access via `http://<host>:12393/admin/`. History fallback served by `StaticFiles(..., html=True)`.
- `vite.config.ts.base`: `/admin/` in production build, `/` in dev (so :5173 root works).
- Bundle target: gzipped < 800KB total. Live2DStage and pixi must be `React.lazy` / dynamic import to keep main chunk light.

### Security (P0 minimum)

- No auth middleware. Relies on OLV `conf.yaml` host binding (default 127.0.0.1) per 说明书 §12.3.
- Server-side masking on `/api/runtime/snapshot`: any field whose key matches `/api[_-]?key|token|secret|password/i` is replaced with `****<last4>` (or `****` if shorter).
- Masking is a serialization-layer concern in `admin_routes.py`; never trust the frontend to mask.

## Backend Changes

### `src/open_llm_vtuber/admin_routes.py` (NEW)

```python
def init_admin_routes(default_context_cache: ServiceContext) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health") -> HealthResponse
    @router.get("/runtime/snapshot") -> SnapshotResponse
    @router.get("/runtime/recent-errors") -> RecentErrorsResponse

    return router
```

#### `GET /api/health`

```json
{
  "status": "ok|degraded|error",
  "components": {
    "olv":      { "status": "ok",   "detail": "running",         "updated_at": "ISO8601" },
    "asr":      { "status": "ok",   "provider": "sherpa_onnx",   "updated_at": "..." },
    "tts":      { "status": "ok",   "provider": "edge_tts",      "updated_at": "..." },
    "vad":      { "status": "ok",   "updated_at": "..." },
    "mcp":      { "status": "off",  "online_servers": 0, "total_servers": 0, "updated_at": "..." },
    "ue":       { "status": "off",  "detail": "not_configured",  "updated_at": "..." },
    "platform": { "status": "off",  "detail": "not_configured",  "updated_at": "..." }
  },
  "version": "<git short or package version>",
  "uptime_s": 12345
}
```

- `mcp` / `ue` / `platform` always `off` in P0 (real wiring belongs to specs A/B/C). The schema is fixed now so later specs only fill values.
- Component `status` values: `ok | busy | warn | err | off`.
- `version` resolves at startup; if git is unavailable falls back to `pyproject.toml` version.

#### `GET /api/runtime/snapshot`

```json
{
  "ports": [
    { "name": "OLV WebSocket / FastAPI", "port": 12393, "bound_host": "127.0.0.1", "status": "ok" },
    { "name": "UE WebSocket",            "port": 10002, "bound_host": null, "status": "off" },
    { "name": "TTS Wrapper",             "port": 50005, "bound_host": null, "status": "off" }
  ],
  "config": {
    "asr_provider": "sherpa_onnx",
    "tts_provider": "edge_tts",
    "agent_provider": "basic_memory",
    "llm_provider": "openai_compatible_llm",
    "llm_base_url": "https://api.openai.com/v1",
    "llm_api_key_masked": "sk-****abcd"
  },
  "current_session": null
}
```

- Pulls from `ServiceContext` + `config_manager`. Port `status: ok` only when actually listening (probe `is_port_in_use` against `bound_host:port`).
- Masking happens during serialization; raw key never leaves the process.

#### `GET /api/runtime/recent-errors`

```json
{
  "errors": [
    { "ts": "ISO8601", "level": "ERROR", "module": "asr", "message": "...", "request_id": "uuid|null" }
  ]
}
```

- Backed by an in-process `collections.deque(maxlen=200)` populated by a loguru sink installed at server startup.
- Sink filter: `record["level"].no >= WARNING`.
- `module` derives from `record["name"]` (last path segment).

### `server.py` edits (~8 lines)

1. Install loguru sink to memory deque on startup; expose deque via `ServiceContext` (or a module-level singleton imported by `admin_routes`).
2. `from .admin_routes import init_admin_routes` and `app.include_router(init_admin_routes(default_context_cache))`.
3. `app.mount("/admin", StaticFiles(directory="admin-frontend/dist", html=True), name="admin")` guarded by existence check; if missing, log a one-line info "admin-frontend dist not built; /admin disabled" and continue.

### WebSocket

Zero changes. admin-frontend connects to `/client-ws` as another client. All required message types already exist: `audio`, `audio-play-start`, `audio-play-request`, `full-text`, `user-input-transcription`, `mic-audio-data`, `interrupt-signal`, `fetch-history-list`, `fetch-history`, `create-new-history`, `set-model-and-conf`, `heartbeat`, `control`.

If a need surfaces during implementation, that becomes the first amendment to this spec rather than ad-hoc additions.

Verified at design time against `src/open_llm_vtuber/websocket_handler.py` and related modules:

- Inbound (client → server): `mic-audio-data`, `mic-audio-end`, `text-input`, `interrupt-signal`, `fetch-history-list`, `fetch-history`, `create-new-history`, `delete-history`, `audio-play-start`, `fetch-configs`, `switch-config`, `fetch-backgrounds`, `heartbeat`.
- Outbound (server → client): `full-text`, `audio`, `set-model-and-conf`, `new-history-created`, `history-data`, `history-list`, `user-input-transcription`, `control` (text values: `start-mic`, `interrupt`, `mic-audio-end`, `conversation-chain-start`, `conversation-chain-end`), `error`.

`ws-protocol.ts` mirrors this list precisely.

## Frontend Architecture

### Routing

| Path | Page | Side-nav |
| --- | --- | --- |
| `/admin/` | redirect → `/admin/overview` | — |
| `/admin/overview` | OverviewPage | 总览 |
| `/admin/conversation` | ConversationPage | 对话控制台 |
| `/admin/conversation/:sessionId` | ConversationPage (preselect) | 对话控制台 |
| `/admin/avatars` | Placeholder, disabled | 数字人 🚫 |
| `/admin/mcp` | Placeholder, disabled | MCP 工具 🚫 |
| `/admin/config` | Placeholder, disabled | 配置 🚫 |
| `/admin/logs` | Placeholder, disabled | 日志与调试 🚫 |
| `*` | NotFoundPage | — |

Disabled nav items render as gray with a tooltip "敬请期待"; clicking them does nothing.

### Shell

```
┌──────────────────────────────────────────────────────────────┐
│ TopBar (h-14)                                                │
│  [Open-LLM-VTuber 控制台]      [● 全局健康] [刷新] [告警] [设置] │
├────────────┬─────────────────────────────────────────────────┤
│ SideNav    │                                                 │
│ (w-56)     │                  <Outlet />                     │
│  总览      │                                                 │
│  对话控制台│                                                 │
│  数字人 🚫 │                                                 │
│  MCP 工具🚫│                                                 │
│  配置 🚫   │                                                 │
│  日志 🚫   │                                                 │
│ ─────      │                                                 │
│  v1.2.3    │                                                 │
│  127.0.0.1 │                                                 │
│  WS :12393 │                                                 │
└────────────┴─────────────────────────────────────────────────┘
```

TopBar right side is intentionally minimal (per 说明书 §9.1): global title, GlobalHealthBadge, refresh, alerts entry, settings entry. No per-session info, no current-agent, no current-avatar (those live on their respective pages).

SideNav bottom metadata block: version / bound host / OLV WS port / MCP port (MCP shown as `:N/A` in P0).

### Design tokens

`tailwind.config.ts` extends shadcn defaults:

```ts
colors: {
  status: {
    ok:   'hsl(160 60% 42%)',   // green: online / running
    busy: 'hsl(214 90% 52%)',   // blue: in progress
    warn: 'hsl(33 95% 55%)',    // orange: warning
    err:  'hsl(0 82% 56%)',     // red: error
    off:  'hsl(220 12% 65%)',   // gray: not enabled
  }
}
borderRadius: { sm: '4px', DEFAULT: '6px', md: '8px' }
```

Backgrounds: `bg-slate-50` workspace, `bg-white` panels, `border-slate-200` lines. Touch: main buttons `min-h-11`, table rows `min-h-11`.

shadcn components to install: `button card badge tabs separator dialog sheet dropdown-menu tooltip skeleton input textarea scroll-area`.

### State stores

| Store | Fields | Persistence |
| --- | --- | --- |
| `useConnectionStore` | `wsStatus`, `wsLastError`, `clientUid`, `heartbeatAt` | none |
| `useSessionStore` | `currentSessionId`, `messages[]`, `broadcastState`, `historyList[]` | none |
| `useSettingsStore` | `live2dPreviewEnabled` (default false), `audioMuted`, `locale` (zh-CN default) | localStorage |

`broadcastState`: `idle | listening | recognizing | thinking | speaking | interrupted | completed | error`.

TanStack Query intervals: health 5s, snapshot 30s, recent-errors 10s. TopBar refresh button invalidates all three query keys.

### WS client

`src/lib/ws-client.ts`:

```ts
class OlvWsClient {
  constructor(url: string)
  connect(): void                         // exp backoff 1s..30s
  send(msg: WSMessage): void
  on(type: MessageType, handler): () => void
  close(): void
}
```

- Singleton owned by `App.tsx` (connect on mount, close on unmount).
- Heartbeat: send `heartbeat` every 25s; if no message received for 60s, mark disconnected and reconnect.
- On message: dispatch by `type` to registered handlers; mirror connection events into `useConnectionStore` and conversation events into `useSessionStore`.

Protocol types in `ws-protocol.ts` are hand-written to mirror `websocket_handler.py`'s `MessageType` and `WSMessage`. No codegen.

### i18n

- zh-CN default. en-US selectable from settings entry (P0: settings popover stores locale only; full settings page is deferred).
- File layout: `src/locales/<locale>/{common,overview,conversation}.json`.
- 兜底文案 (说明书 §9.5) bound to `common.fallback.*` keys.

## Overview Page

Three rows per 说明书 §9.3.1.

### Row 1: Health cards (grid)

`grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4`, six `<HealthCard>`s.

| Card | Data sources | Sub-status | Action button |
| --- | --- | --- | --- |
| OLV 服务 | `health.olv` + `snapshot.ports[0]` + `snapshot.uptime_s` | port, bound_host, uptime | 测试连接 (loop ping `/api/health`, result toast) |
| 语音输入 / ASR | `health.asr` + `snapshot.config.asr_provider` | provider name | 测试 ASR — clickable, P0 shows toast "待接入" |
| TTS | `health.tts` + `snapshot.config.tts_provider` | provider name | 测试 TTS — clickable, P0 shows toast "待接入" |
| MCP | `health.mcp` | "未配置 / N online / total M" | "前往 MCP 工具页" — disabled with tooltip (target page not built) |
| UE 数字人 | `health.ue` | "未连接 / 未配置" | 测试 UE 连接 — clickable, P0 shows toast "待接入" |
| 客户平台 | `health.platform` | "未配置 / 已连接 / 鉴权失败" | 测试连接 — clickable, P0 shows toast "待接入" |

Convention: actions that *would* call a non-existent backend endpoint are rendered as enabled buttons that show a "待接入" toast on click (so the UI shape is honest about what's been wired). Actions that link to *unbuilt pages* are rendered as disabled with tooltip (so the user is not misled into thinking the target exists).

`<HealthCard>` props: `title`, `status: ok|busy|warn|err|off`, `subStatus: string`, `metaRows: { label; value }[]`, `actionLabel?`, `onAction?`, `updatedAt?`, `isLoading?`.

`status: off` → card body opacity-60 + action disabled.

Loading: `<Skeleton>` over content area; outer frame stays.

### Row 2: Port status table

Renders `snapshot.ports` as a shadcn `<Table>`:

| 名称 | 端口 | 绑定地址 | 状态 |
| --- | --- | --- | --- |
| OLV WebSocket / FastAPI | 12393 | 127.0.0.1 | ● 在线 |
| UE WebSocket | 10002 | — | ○ 未启用 |
| TTS Wrapper | 50005 | — | ○ 未启用 |

Trailing "展开自定义 MCP 端口" collapsible (P0 empty state: "暂无配置").

### Row 3: Recent errors + Quick test

Left col-span-2: recent errors list (consumes `/api/runtime/recent-errors`). Columns: 时间 / 模块 / 级别 (warn 橙 / err 红 badge) / 摘要. Click row → drawer with full `message` + `request_id`. Empty: `<EmptyState>` "暂无异常".

Right col-span-1: quick test buttons.
- 测试文本问答 → `navigate('/admin/conversation')` and prefill composer with example "你好，请简单介绍下自己".
- 测试语音输入 / 测试 TTS / 测试 MCP 工具 / 测试 UE 连接 → disabled + tooltip "待接入".

### Global health badge

Derived from `useHealth()`:

- All non-`off` components are `ok` → green "全部正常"
- Any `err` → red "X 个组件异常"
- Else any `warn` → orange "X 个组件告警"
- All `off` → gray "未配置"

## Conversation Console Page

Three columns: `grid grid-cols-[280px_1fr_360px] h-[calc(100vh-3.5rem)]`. Below 1280px viewport, StagePanel collapses to a floating button (overlay sheet on demand).

### Left: HistoryPanel (w-72)

- Top: `<Input>` (local-filter session titles) + `<Button>` "新建会话".
- List: `<ScrollArea>` of `<HistoryItem>`:
  - title = first 24 chars of first user question
  - summary = first 40 chars of first assistant answer
  - relative time
  - status badge: 已完成 / 进行中 / 已中断 / 异常
  - highlight: `currentSessionId` match → blue left bar + `bg-slate-100`
- Source: WS `fetch-history-list` → `historyList` in `useSessionStore`.
- New session: WS `create-new-history`; on `new-history-created`, switch id, clear `messages`.

### Center: ConversationPanel (flex-1)

**Header bar (h-14, sticky)**

- Left: current session title + subline (`会话 ID · N 条消息`).
- Center: `<BroadcastStateBadge>`:

  | state | color | label |
  | --- | --- | --- |
  | idle | gray | 待输入 |
  | listening | blue (pulse) | 录音中 |
  | recognizing | blue | 识别中 |
  | thinking | blue | 思考中 |
  | speaking | blue | 播报中 |
  | interrupted | orange | 已打断 |
  | completed | green (auto-fade 2s) | 已完成 |
  | error | red | 异常 |

- Right: `<Button variant="destructive">` 打断播报 (enabled only when `speaking`).

**Message list (scroll area, auto-scroll to bottom)**

```ts
type Message =
  | { kind: 'user-text';   id; text; ts }
  | { kind: 'user-voice';  id; text; confidence?; ts }
  | { kind: 'assistant';   id; text; ts; broadcastDone: boolean; audioSegments: AudioSegment[]; processSummary?: ProcessSummary }
  | { kind: 'transition';  id; text; ts }
  | { kind: 'error';       id; text; ts; code? }
```

Bubble rules:
- user → right-aligned, dark bg, `max-w-[70%]`.
- assistant → left-aligned, white bg, 4px left status bar (blue speaking / green completed / orange interrupted).
- transition → centered, small muted text, no bubble.
- error → left-aligned, red border + tinted bg, includes error code.
- assistant footer: `<Button variant="ghost" size="sm">查看过程</Button>` opens `<ProcessDrawer>` (right sheet) showing `request_id`, tool call summary, `latency_ms`, raw JSON (folded). P0 placeholder: "暂无过程信息" until spec A wires MessagePart.

WS → message mapping:

| WS message | Action |
| --- | --- |
| `full-text` (user echo) | append `user-text` |
| `user-input-transcription` | append `user-voice` |
| `audio` | append slice to current assistant message's `audioSegments`; enqueue to AudioQueueController |
| `full-text` assistant / `set-conversation-text` | append/append-chunk `assistant` |
| `control` text=`conversation-chain-start` | broadcastState → thinking |
| `audio-play-start` | broadcastState → speaking |
| `control` text=`conversation-chain-end` | broadcastState → completed |
| `error` | append `error`; broadcastState → error |
| `control` text=`interrupt` (server-side) OR local interrupt action | mark current assistant `broadcastDone=false`; state → interrupted |

Server-side `control` text values observed in OLV: `start-mic`, `interrupt`, `mic-audio-end`, `conversation-chain-start`, `conversation-chain-end`. Client-side `interrupt-signal` is the *outbound* request sent when the user clicks 打断.

**Composer (h-24)**

- Textarea: placeholder "输入要让数字人回答的问题"; Enter sends / Shift+Enter newline; 1000-char cap.
- Mic button: tap to toggle / long-press to record; state → listening → recognizing.
- Send button: disabled when input empty or `broadcastState in [thinking, speaking]`.
- Interrupt button: always visible, highlighted only when `speaking`.
- Text send → WS `text-input` (existing). Voice → MediaRecorder → PCM16 16kHz → slice and send `mic-audio-data`. Self-write a ~100-line minimal version that mirrors the submodule's slice protocol; if reality diverges, that is the first spec amendment point.

### Right: StagePanel (w-[360px])

**Live2D preview (collapsible card, default collapsed via `useSettingsStore.live2dPreviewEnabled`)**

- Expanded: `<Live2DStage>` (React.lazy).
  - Internals: pixi.js + pixi-live2d-display.
  - Init: WS `fetch-configs` → receive `set-model-and-conf` → load model3.json.
  - Expressions/motions: react to `audio.actions.expressions[]` / `actions.motions[]` from the `audio` message payload.
  - Lip sync: subscribe to `audioQueueController.volumeNode` (AnalyserNode); each frame compute average and set `ParamMouthOpenY`.
  - Failure fallback: model load error → "Live2D 模型加载失败 · [重试]"; does not block other panels.
- Collapsed: placeholder "Live2D 预览已折叠 · [展开]" (canvas unmounted, CPU drops).

**Broadcast status card (always visible, compact)**

- Current message id (short) + remaining slice count.
- Audio queue badge: `<Badge>N</Badge> 待播片段`.
- Controls:
  - Volume slider (binds `audioQueueController.gain`).
  - Mute toggle (local audio only, does not interrupt).
  - Replay button: `POST /api/runtime/replay` (P0 disabled with tooltip "待接入"; placeholder UI only).

### AudioQueueController

`src/components/avatar/audio-queue-controller.ts`:

```ts
class AudioQueueController {
  enqueue(b64Wav: string, meta: { sliceId: string; messageId: string }): void
  pause(): void
  resume(): void
  clear(): void
  readonly currentSlice: SliceState | null
  on('start' | 'end' | 'progress' | 'cleared', cb): () => void
  readonly volumeNode: AnalyserNode
}
```

- Single `AudioContext`. Chain: `BufferSource → GainNode → AnalyserNode → destination`.
- base64 → ArrayBuffer → `decodeAudioData` → serial playback (a slice plays in full before the next starts).
- `clear()` stops the current source and empties the queue.
- AudioContext autoplay unlock: call `audioContext.resume()` synchronously inside the first user interaction (composer focus, send click, or mic press).

WS wiring (in `App.tsx`):
- `ws.on('audio', m => audioQueue.enqueue(m.audio, ...))` — `audio` payload includes `audio` (base64 WAV), `volumes[]` (precomputed per-chunk volume — usable for lip sync as an alternative to AnalyserNode), `slice_length`, `display_text`, `actions`.
- `ws.on('audio-play-start', () => setBroadcastState('speaking'))`
- `ws.on('control', m => { if (m.text === 'interrupt') audioQueue.clear() })`

### Interrupt flow (说明书 §4.4)

User clicks 打断 OR starts new voice input:

1. `audioQueueController.clear()` (local audio stops immediately).
2. WS send `interrupt-signal`.
3. broadcastState → `interrupted`.
4. Current assistant message → `broadcastDone: false`.
5. After 2s, state auto-returns to `idle`.

## Testing

| Layer | Tool | Targets |
| --- | --- | --- |
| Backend unit | pytest + httpx AsyncClient | Three GETs; masking; recent-errors sink ring buffer |
| Frontend unit | vitest + @testing-library/react | AudioQueueController, ws-client (reconnect/heartbeat with fake timers), MessageList kind branches, ProcessDrawer toggle, HealthCard rendering, GlobalHealthBadge derivation |
| Frontend types | `tsc --noEmit` strict | clean |
| Lint | eslint + prettier --check | clean |
| Backend lint/types | ruff check / ruff format --check | clean (existing repo standard) |

E2E (Playwright) intentionally out of scope.

Live2D smoke is manual (WebGL not exercised by vitest).

CI: do not modify `.github/workflows/` this phase. Local gate: `npm run typecheck && npm run lint && npm run test && npm run build` must pass before merge.

## Manual Acceptance Checklist

| Item | Action | Expected |
| --- | --- | --- |
| Overview live | `uv run run_server.py`, open `/admin/overview` | 6 cards populate within 5s; OLV/ASR/TTS at least `ok`; MCP/UE/Platform show "未启用" gray badge |
| Global health badge | Kill ASR or misconfigure provider, restart | TopBar red "X 个组件异常" |
| Port table | Overview row 2 | 12393 online, 10002/50005 not enabled, bound_host correct |
| Recent errors | Provoke a TTS failure | Row 3 shows ERROR entry; clicking opens drawer with message + request_id |
| Quick test text | Click 测试文本问答 | Navigates to conversation page; composer prefilled with example |
| Conversation new | Click 新建会话 | History list adds entry; message stream clears; URL updates with new sessionId |
| Conversation switch | Click old session | Message stream replays; URL syncs |
| Text question | Type and submit | User bubble appears; state thinking → speaking; assistant bubble streams while audio plays |
| Voice question | Long-press mic | State listening → recognizing → thinking → speaking |
| Interrupt | Click 打断 during speaking | Audio stops immediately; queue cleared; state interrupted; 2s later returns to idle |
| Live2D preview | Expand StagePanel | Model loads; mouth animates with audio; expressions react to `actions.expressions` |
| Live2D collapse | Collapse StagePanel | Canvas unmounts; CPU drops |
| Masking | Configure a real API key, hit `/api/runtime/snapshot` | Returns `sk-****abcd` form; raw key absent |
| Static serve | After `npm run build`, hit `http://127.0.0.1:12393/admin/` | Page renders; refresh on subroute returns 200 (history fallback) |
| Touch | Tap main buttons on touchscreen | All hit targets ≥44px; no hover-only affordances |

## Performance Targets

- Overview first paint < 1.5s (including first `/api/health` round-trip).
- Conversation send → first audio slice playback < 3s (depends on backend; this phase only verifies the link works).
- Gzipped main bundle < 800KB. Live2D and pixi split into a lazy chunk.

## Deliverables

1. `admin-frontend/` workspace (with README: dev start, build, deploy path).
2. `src/open_llm_vtuber/admin_routes.py` + `server.py` edits.
3. `tests/test_admin_routes.py`.
4. `docs/admin-frontend.md`: architecture, API contract, WS protocol table, future-page roadmap placeholders.
5. README snippet documenting how operators start and verify admin-frontend on site.

## REQ / FM Coverage

This spec covers:

- REQ-012 (React + TS + shadcn frontend), partial FM-005 (skeleton).
- FM-002 (health panel), FM-003 (port diagnostics) via Overview.
- REQ-015 (history / text + voice / interrupt / new session), FM-006 via Conversation Console.
- REQ-014 + FM-004 partial + FM-042 (masking) via snapshot serialization.
- REQ-018 (frontend ↔ backend API/WS).
- 说明书 §9.5 fallback copy.

Not covered (deferred):

- FM-007 数字人 page (avatar grid + UE resource management).
- FM-008 MCP tools page.
- FM-009 logs & debug standalone page (only a slice via Overview's "最近异常").
- FM-014~018 backend pipeline / MessagePart / three-agent system (spec A).
- FM-024~028 customer platform adapter (spec B).
- FM-038~041 UE WebSocket client and avatar switching (spec C).
- Full six-tab configuration surface.

## Risks and Dependencies

- Live2D model path depends on OLV's existing `set-model-and-conf` message, which is already emitted by `_handle_init_config_request`. No backend change required.
- Voice PCM slice protocol mirrors the existing submodule's `mic-audio-data` format. If implementation finds the protocol diverges in practice, that is the first amendment to this spec.
- Browser AudioContext autoplay policy: first audio playback must follow a user gesture. Call `audioContext.resume()` synchronously in the first composer interaction.
- shadcn/ui CLI initializes generated files into the workspace. README documents the steps; we do not commit speculative pre-generated files.
- Bundle size: pixi-live2d-display adds significant weight. Use `React.lazy` for the stage and verify the gzipped budget at build time.

## Acceptance

P0 acceptance is satisfied when:

- Admin-frontend boots at `/admin/` from a clean `git pull && uv sync && (cd admin-frontend && npm install && npm run build) && uv run run_server.py`.
- Overview page renders the six health cards, port table, recent errors, and quick test column with live data within 5s of load.
- Conversation Console supports the full text + voice + interrupt + history flow against the existing `/client-ws` protocol with no backend protocol changes.
- Local Live2D preview can be enabled and animates lip-sync from the audio queue.
- Sensitive config values never appear unmasked in `/api/runtime/snapshot`.
- All tests, type checks, and lints listed in §Testing pass locally.
