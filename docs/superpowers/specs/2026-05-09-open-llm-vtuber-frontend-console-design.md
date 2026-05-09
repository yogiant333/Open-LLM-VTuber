# Open-LLM-VTuber Frontend Console Redesign

## Scope

Redesign the existing Open-LLM-VTuber runtime frontend into a smart-human-console style runtime console.

The first phase is not a full management backend. It focuses on:

- A console-style chat runtime page.
- A visible digital-human stage inside the chat experience.
- Real Live2D support preserved from the current frontend.
- Real LiveTalking WebRTC support.
- UE5 / Pixel Streaming placeholder support for later integration.
- A compact digital-human settings drawer or panel.

Out of scope for phase one:

- Full six-page operations backend.
- Independent overview, MCP tools, logs, and configuration pages.
- Full UE5 Data Channel control.
- Complex voice-clone or voice-management workflows.

## Source And Delivery Model

The current `frontend` directory is a git submodule pointing to:

```text
https://github.com/Open-LLM-VTuber/Open-LLM-VTuber-Web
```

It currently tracks the `build` delivery branch and contains built static assets. Development should use the Web submodule source branch, then build and publish the static output back through the existing frontend delivery path.

The `smart-human-console` directory and `D:\AI\fay\docs\智慧数字人一体机前端页面设计文档.md` are references for interaction style, layout density, and enterprise console tone. They are not the primary implementation target.

## Product Direction

The frontend should feel like a practical runtime console for on-site digital-human demos:

- Clear current state.
- Fast chat operation.
- Prominent digital-human display.
- Low-friction text, voice, send, and interrupt controls.
- Debug/process details folded away by default.
- No marketing hero, decorative page, or low-density landing screen.

The visual language should follow the smart-human-console reference:

- Light gray workbench background.
- White panels with light borders.
- Muted teal/blue for primary actions and online states.
- Orange/red for warning and error states.
- 6px to 8px radii for panels and controls.
- Medium-to-high information density suitable for repeated use.

## Page Layout

The runtime page uses a three-zone workspace with a top status bar.

```text
Top status bar
  Open-LLM-VTuber identity, global connection state, refresh, settings

Left sidebar
  Connection status
  Current session summary
  Recent sessions
  New session action
  Digital-human settings entry

Center console
  Current conversation title and state
  Message stream
  Folded process details
  Text input
  Voice input
  Send
  Interrupt

Digital-human stage
  Renderer mode switch: Live2D / LiveTalking / UE5
  Avatar render surface
  Renderer connection state
  Renderer-specific compact controls
```

The layout should prioritize the digital-human stage and the current conversation. The page should not include scene selection, agent selection, or complex scheduling controls in phase one.

## Avatar Renderer Architecture

Add a renderer abstraction so the chat runtime does not directly couple itself to a single digital-human engine.

```text
Open-LLM-VTuber WebSocket
  -> message dispatcher
    -> conversation state
    -> audio/control events
    -> AvatarRenderer
       -> Live2DRenderer
       -> LiveTalkingRenderer
       -> UE5RendererPlaceholder
```

The renderer interface should cover:

- Initialize renderer.
- Clean up renderer.
- Report ready, connecting, error, and offline states.
- Consume model/config messages where relevant.
- Consume audio messages.
- Consume expression or motion events where relevant.
- Handle interrupt.

The renderer abstraction should keep LiveTalking and future UE5 integration from spreading special-case logic across the chat page.

## Live2D Renderer

Live2D remains the default renderer and must preserve existing behavior:

- Load models from the current `set-model-and-conf` flow.
- Use existing Live2D canvas / adapter capability.
- Apply expression events from `audio.actions.expressions`.
- Preserve audio playback and mouth/volume behavior.
- Support interruption by stopping local playback/queues where the current frontend already supports it and sending the backend interrupt signal.

The redesign must not regress the current Live2D runtime path.

## LiveTalking Renderer

LiveTalking is installed locally at:

```text
D:\AI\LiveTalking
/mnt/d/AI/LiveTalking
```

Default phase-one configuration:

```text
service_url = http://localhost:8010
avatar_id = wav2lip256_avatar1
transport = webrtc
```

The renderer should:

1. Create an `RTCPeerConnection`.
2. Request video/audio receive tracks.
3. Call `POST /offer`.
4. Store the returned `sessionid`.
5. Display the returned WebRTC media stream in the digital-human stage.
6. On Open-LLM-VTuber `audio` messages, convert base64 WAV to a `Blob`.
7. Send audio to `POST /humanaudio` with `sessionid` and `file`.
8. On interrupt, call `POST /interrupt_talk` and send the backend `interrupt-signal`.

The renderer may optionally call `POST /is_speaking` to sync speaking state, but this is not required for the first implementation.

Recommended LiveTalking launch command for manual verification:

```bash
cd /mnt/d/AI/LiveTalking
python app.py --transport webrtc --model wav2lip --avatar_id wav2lip256_avatar1
```

## UE5 Placeholder Renderer

UE5 support is a phase-one placeholder. It should make the future integration path visible without pretending the control path is complete.

The placeholder should provide:

- Renderer mode named `UE5`.
- Pixel Streaming URL input or configured default.
- Embedded preview area or iframe placeholder.
- Connection state display.
- "待连接 Pixel Streaming" or equivalent state when not configured.

The first phase does not implement:

- Pixel Streaming Data Channel command mapping.
- UE animation, expression, or camera control.
- UE local bridge service.

The renderer boundary should leave room for later mapping from generic avatar events to Pixel Streaming Data Channel or a local UE bridge.

## Chat Console Behavior

The console preserves existing text and voice flows:

- Text input sends user text to the backend.
- Voice input sends microphone/audio data using the current frontend protocol.
- Messages from the backend append to the conversation stream.
- Assistant process details stay folded under "查看过程" or an equivalent disclosure.
- Interrupt is a high-priority action available near the conversation header and input controls.

The message stream should support:

- User question.
- Digital-human answer.
- Transition text.
- Error message.
- Folded process details with request id, tool summary, latency, and raw detail only when expanded.

## Digital-Human Settings

Phase one should use a drawer, side panel, or compact settings surface instead of a full separate page.

It should include:

- Current renderer mode.
- Live2D model selection using the existing model list.
- LiveTalking service URL.
- LiveTalking avatar id.
- LiveTalking connection state and reconnect action.
- UE5 Pixel Streaming URL.
- Voice binding state as read-only summary.

It should not include:

- Business-role naming.
- Scene binding.
- Agent binding.
- Full voice-clone management.

## Error Handling

The UI must keep chat usable when a renderer fails.

Required states:

- Live2D model load failure: show a stage error while chat remains usable.
- LiveTalking service unavailable: show disconnected state, service URL, and reconnect action.
- LiveTalking `/offer` failure: advise checking that LiveTalking is running in WebRTC mode.
- LiveTalking `/humanaudio` failure: keep the chat answer visible and mark audio forwarding as failed.
- Interrupt failure: still send backend interrupt and show renderer interrupt confirmation failed.
- UE5 unconfigured: show explicit placeholder state, not an online state.

Sensitive values should not be exposed in normal UI or logs.

## Testing And Verification

Implementation should include focused tests where the frontend test stack supports them:

- Renderer mode state transitions.
- Message dispatcher routing audio to the active renderer.
- Base64 WAV to Blob conversion for LiveTalking.
- LiveTalking error states for failed `/offer` and failed `/humanaudio`.
- UI state for renderer ready, connecting, offline, and error.

Manual verification checklist:

- Live2D mode loads the existing model and preserves current chat behavior.
- Text question receives an answer and displays it in the console.
- Voice input still works.
- Interrupt stops or marks the current playback as interrupted.
- LiveTalking mode connects to `http://localhost:8010/offer`.
- LiveTalking video stream appears in the digital-human stage.
- Open-LLM-VTuber audio is forwarded to LiveTalking `/humanaudio`.
- LiveTalking interrupt calls `/interrupt_talk`.
- UE5 mode shows a clear placeholder state.
- Build output can be served by the main Open-LLM-VTuber backend static mount.

## Acceptance Criteria

- The existing runtime frontend is redesigned as a smart-human-console style runtime console.
- The main page includes a digital-human display region.
- Live2D remains functional as the default renderer.
- LiveTalking can be selected and connected through WebRTC.
- LiveTalking receives generated audio through `/humanaudio`.
- UE5 is represented as a future Pixel Streaming integration placeholder.
- The chat UI keeps text, voice, send, and interrupt controls visible and touch-friendly.
- Debug/process details are folded by default.
- The implementation uses the Web frontend submodule source workflow rather than editing minified build assets directly.
