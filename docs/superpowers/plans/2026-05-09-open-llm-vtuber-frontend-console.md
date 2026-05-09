# Open-LLM-VTuber Frontend Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the existing Open-LLM-VTuber Web runtime frontend into a smart-human-console style chat console with a digital-human stage supporting Live2D, LiveTalking, and a UE5 placeholder.

**Architecture:** Work in the `frontend` submodule source branch from `Open-LLM-VTuber-Web`, not in minified build assets. Add an avatar renderer context that owns renderer mode/config/status, route backend audio in `WebSocketHandler` to either the existing Live2D audio queue or LiveTalking, and replace the old overlay layout with a three-zone console workspace.

**Tech Stack:** React 18, TypeScript, Vite/Electron Vite, Chakra UI 3, existing Live2D WebSDK, WebSocket backend protocol, LiveTalking WebRTC HTTP APIs.

---

## File Structure

Primary implementation happens in the Web frontend submodule source tree:

- Modify: `frontend/src/renderer/src/App.tsx`
  - Replace the current dark overlay layout with the runtime console shell.
  - Wrap the app with `AvatarRendererProvider`.
- Create: `frontend/src/renderer/src/context/avatar-renderer-context.tsx`
  - Store active renderer mode, LiveTalking config, UE5 config, renderer state, and actions.
- Create: `frontend/src/renderer/src/types/avatar-renderer.ts`
  - Shared renderer mode/config/status/audio event types.
- Create: `frontend/src/renderer/src/utils/avatar-audio.ts`
  - Convert backend base64 WAV strings to `Blob`.
- Create: `frontend/src/renderer/src/services/livetalking-client.ts`
  - Encapsulate `/offer`, `/humanaudio`, `/interrupt_talk`, and cleanup.
- Create: `frontend/src/renderer/src/components/console/console-shell.tsx`
  - Top-level console layout.
- Create: `frontend/src/renderer/src/components/console/status-bar.tsx`
  - Top global status bar.
- Create: `frontend/src/renderer/src/components/console/session-sidebar.tsx`
  - Connection/session/history/settings column using existing contexts.
- Create: `frontend/src/renderer/src/components/console/chat-console.tsx`
  - Current conversation panel and message list.
- Create: `frontend/src/renderer/src/components/console/digital-human-stage.tsx`
  - Renderer mode switch and stage container.
- Create: `frontend/src/renderer/src/components/console/digital-human-settings.tsx`
  - Compact settings drawer/panel for renderer configuration.
- Modify: `frontend/src/renderer/src/services/websocket-handler.tsx`
  - Route audio messages by active renderer mode.
  - Preserve Live2D default behavior.
- Modify: `frontend/src/renderer/src/hooks/utils/use-interrupt.ts`
  - Ask active renderer to interrupt in addition to current backend/Live2D interrupt behavior.
- Modify: `frontend/src/renderer/src/hooks/footer/use-footer.ts`
  - Expose the existing send handler to the console input button.
- Modify: `frontend/src/renderer/src/components/canvas/live2d.tsx`
  - Accept console-stage rendering without pet-mode pointer behavior leaking into the new console layout.
- Modify: `frontend/src/renderer/src/locales/en/translation.json`
  - Add console and avatar renderer strings.
- Modify: `frontend/src/renderer/src/locales/zh/translation.json`
  - Add Chinese console and avatar renderer strings.

Verification:

- Run inside `frontend`: `npm run typecheck:web`
- Run inside `frontend`: `npm run build:web`
- Manual browser check through `npm run dev:web`
- Main repo static serving check after build output is published to the submodule build path.

## Task 1: Prepare Frontend Source Branch And Baseline

**Files:**
- Modify: `frontend` submodule checkout only
- Read: `frontend/package.json`
- Read: `frontend/src/renderer/src/App.tsx`

- [ ] **Step 1: Switch the submodule to a source branch**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git fetch origin main build
git switch -c console-redesign origin/main
```

Expected: `frontend` is on a new local branch `console-redesign` based on `origin/main`.

- [ ] **Step 2: Install dependencies if missing**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm install
```

Expected: dependencies install without dependency resolution errors.

- [ ] **Step 3: Run baseline typecheck**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS. If it fails before changes, save the exact error in the task handoff and do not start feature edits until the baseline failure is understood.

- [ ] **Step 4: Run baseline web build**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run build:web
```

Expected: PASS and Vite emits web build output.

- [ ] **Step 5: Commit branch preparation only if files changed**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git status --short
```

Expected: either no changes, or only lockfile/dependency metadata from `npm install`. If lockfiles changed, commit them with:

```bash
git add package-lock.json package.json
git commit -m "Keep web frontend dependencies reproducible" \
  -m "Dependency metadata was refreshed before the console redesign so later feature commits are easier to review." \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Tested: npm run typecheck:web; npm run build:web"
```

## Task 2: Add Renderer Types And Base64 Audio Utility

**Files:**
- Create: `frontend/src/renderer/src/types/avatar-renderer.ts`
- Create: `frontend/src/renderer/src/utils/avatar-audio.ts`

- [ ] **Step 1: Create shared renderer types**

Create `frontend/src/renderer/src/types/avatar-renderer.ts`:

```ts
import { AudioPayload } from '@/services/websocket-service';

export type AvatarRendererMode = 'live2d' | 'livetalking' | 'ue5';

export type AvatarRendererStatus = 'idle' | 'connecting' | 'ready' | 'speaking' | 'error';

export interface LiveTalkingConfig {
  serviceUrl: string;
  avatarId: string;
  useStun: boolean;
}

export interface Ue5Config {
  pixelStreamingUrl: string;
}

export interface AvatarRendererState {
  mode: AvatarRendererMode;
  status: AvatarRendererStatus;
  statusMessage: string;
  liveTalking: LiveTalkingConfig;
  ue5: Ue5Config;
}

export type AvatarAudioMessage = AudioPayload;

export const defaultAvatarRendererState: AvatarRendererState = {
  mode: 'live2d',
  status: 'idle',
  statusMessage: 'Live2D ready',
  liveTalking: {
    serviceUrl: 'http://localhost:8010',
    avatarId: 'wav2lip256_avatar1',
    useStun: false,
  },
  ue5: {
    pixelStreamingUrl: '',
  },
};
```

- [ ] **Step 2: Create base64 WAV conversion utility**

Create `frontend/src/renderer/src/utils/avatar-audio.ts`:

```ts
export function base64WavToBlob(base64Audio: string): Blob {
  if (!base64Audio) {
    throw new Error('audio payload is empty');
  }

  const normalized = base64Audio.includes(',')
    ? base64Audio.slice(base64Audio.indexOf(',') + 1)
    : base64Audio;

  const binary = window.atob(normalized);
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return new Blob([bytes], { type: 'audio/wav' });
}
```

- [ ] **Step 3: Run typecheck**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS.

- [ ] **Step 4: Commit renderer type foundation**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git add src/renderer/src/types/avatar-renderer.ts src/renderer/src/utils/avatar-audio.ts
git commit -m "Define avatar renderer primitives for the console" \
  -m "The console needs one boundary for Live2D, LiveTalking, and future UE5 rendering so backend message handling does not accumulate renderer-specific state." \
  -m "Constraint: Keep Live2D as the default renderer" \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Tested: npm run typecheck:web"
```

## Task 3: Add LiveTalking Client

**Files:**
- Create: `frontend/src/renderer/src/services/livetalking-client.ts`
- Modify: `frontend/src/renderer/src/utils/avatar-audio.ts`

- [ ] **Step 1: Add a small error helper to the audio utility**

Modify `frontend/src/renderer/src/utils/avatar-audio.ts` to exactly:

```ts
export function base64WavToBlob(base64Audio: string): Blob {
  if (!base64Audio) {
    throw new Error('audio payload is empty');
  }

  const normalized = base64Audio.includes(',')
    ? base64Audio.slice(base64Audio.indexOf(',') + 1)
    : base64Audio;

  const binary = window.atob(normalized);
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return new Blob([bytes], { type: 'audio/wav' });
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return String(error);
}
```

- [ ] **Step 2: Create LiveTalking client**

Create `frontend/src/renderer/src/services/livetalking-client.ts`:

```ts
import { LiveTalkingConfig } from '@/types/avatar-renderer';
import { base64WavToBlob } from '@/utils/avatar-audio';

interface LiveTalkingOfferResponse {
  sdp: string;
  type: RTCSdpType;
  sessionid: string;
}

export class LiveTalkingClient {
  private peerConnection: RTCPeerConnection | null = null;

  private sessionId: string | null = null;

  private remoteStream: MediaStream | null = null;

  constructor(private readonly config: LiveTalkingConfig) {}

  getSessionId(): string | null {
    return this.sessionId;
  }

  getRemoteStream(): MediaStream | null {
    return this.remoteStream;
  }

  async connect(onTrack: (stream: MediaStream) => void): Promise<string> {
    this.disconnect();

    const peerConnection = new RTCPeerConnection({
      sdpSemantics: 'unified-plan',
    } as RTCConfiguration);

    peerConnection.addTransceiver('video', { direction: 'recvonly' });
    peerConnection.addTransceiver('audio', { direction: 'recvonly' });

    peerConnection.addEventListener('track', (event) => {
      const [stream] = event.streams;
      if (stream) {
        this.remoteStream = stream;
        onTrack(stream);
      }
    });

    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);

    const response = await fetch(`${this.config.serviceUrl}/offer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sdp: peerConnection.localDescription?.sdp,
        type: peerConnection.localDescription?.type,
        avatar: this.config.avatarId,
        use_stun: this.config.useStun,
      }),
    });

    if (!response.ok) {
      throw new Error(`/offer failed with HTTP ${response.status}`);
    }

    const answer = (await response.json()) as LiveTalkingOfferResponse;
    this.sessionId = answer.sessionid;
    await peerConnection.setRemoteDescription(answer);
    this.peerConnection = peerConnection;

    return answer.sessionid;
  }

  async sendAudio(audioBase64: string): Promise<void> {
    if (!this.sessionId) {
      throw new Error('LiveTalking session is not connected');
    }

    const formData = new FormData();
    formData.append('sessionid', this.sessionId);
    formData.append('file', base64WavToBlob(audioBase64), 'reply.wav');

    const response = await fetch(`${this.config.serviceUrl}/humanaudio`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`/humanaudio failed with HTTP ${response.status}`);
    }
  }

  async interrupt(): Promise<void> {
    if (!this.sessionId) {
      return;
    }

    const response = await fetch(`${this.config.serviceUrl}/interrupt_talk`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionid: this.sessionId }),
    });

    if (!response.ok) {
      throw new Error(`/interrupt_talk failed with HTTP ${response.status}`);
    }
  }

  disconnect(): void {
    this.peerConnection?.getSenders().forEach((sender) => sender.track?.stop());
    this.peerConnection?.getReceivers().forEach((receiver) => receiver.track?.stop());
    this.peerConnection?.close();
    this.peerConnection = null;
    this.sessionId = null;
    this.remoteStream = null;
  }
}
```

- [ ] **Step 3: Run typecheck**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS.

- [ ] **Step 4: Commit LiveTalking client**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git add src/renderer/src/services/livetalking-client.ts src/renderer/src/utils/avatar-audio.ts
git commit -m "Add a LiveTalking WebRTC client" \
  -m "LiveTalking owns a browser WebRTC session, so the frontend needs a small client that connects /offer, forwards generated WAV audio to /humanaudio, and interrupts /interrupt_talk." \
  -m "Constraint: Default LiveTalking service is expected at http://localhost:8010" \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Tested: npm run typecheck:web"
```

## Task 4: Add Avatar Renderer Context

**Files:**
- Create: `frontend/src/renderer/src/context/avatar-renderer-context.tsx`
- Modify: `frontend/src/renderer/src/App.tsx`

- [ ] **Step 1: Create renderer context**

Create `frontend/src/renderer/src/context/avatar-renderer-context.tsx`:

```tsx
import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from 'react';
import { toaster } from '@/components/ui/toaster';
import { LiveTalkingClient } from '@/services/livetalking-client';
import {
  AvatarAudioMessage,
  AvatarRendererMode,
  AvatarRendererState,
  LiveTalkingConfig,
  Ue5Config,
  defaultAvatarRendererState,
} from '@/types/avatar-renderer';
import { getErrorMessage } from '@/utils/avatar-audio';

interface AvatarRendererContextValue extends AvatarRendererState {
  liveTalkingStream: MediaStream | null;
  setMode: (mode: AvatarRendererMode) => void;
  setLiveTalkingConfig: (config: LiveTalkingConfig) => void;
  setUe5Config: (config: Ue5Config) => void;
  connectLiveTalking: () => Promise<void>;
  consumeLiveTalkingAudio: (message: AvatarAudioMessage) => Promise<void>;
  interruptActiveRenderer: () => Promise<void>;
}

const AvatarRendererContext = createContext<AvatarRendererContextValue | null>(null);

export function AvatarRendererProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AvatarRendererState>(defaultAvatarRendererState);
  const [liveTalkingStream, setLiveTalkingStream] = useState<MediaStream | null>(null);
  const liveTalkingClientRef = useRef<LiveTalkingClient | null>(null);

  const setMode = useCallback((mode: AvatarRendererMode) => {
    if (mode !== 'livetalking') {
      liveTalkingClientRef.current?.disconnect();
      liveTalkingClientRef.current = null;
      setLiveTalkingStream(null);
    }

    setState((current) => ({
      ...current,
      mode,
      status: mode === 'ue5' ? 'idle' : 'idle',
      statusMessage:
        mode === 'live2d'
          ? 'Live2D ready'
          : mode === 'livetalking'
            ? 'LiveTalking disconnected'
            : '待连接 Pixel Streaming',
    }));
  }, []);

  const setLiveTalkingConfig = useCallback((config: LiveTalkingConfig) => {
    liveTalkingClientRef.current?.disconnect();
    liveTalkingClientRef.current = null;
    setLiveTalkingStream(null);
    setState((current) => ({
      ...current,
      liveTalking: config,
      status: current.mode === 'livetalking' ? 'idle' : current.status,
      statusMessage: current.mode === 'livetalking' ? 'LiveTalking disconnected' : current.statusMessage,
    }));
  }, []);

  const setUe5Config = useCallback((config: Ue5Config) => {
    setState((current) => ({
      ...current,
      ue5: config,
      statusMessage: current.mode === 'ue5' && config.pixelStreamingUrl
        ? 'Pixel Streaming configured'
        : current.statusMessage,
    }));
  }, []);

  const connectLiveTalking = useCallback(async () => {
    setState((current) => ({
      ...current,
      mode: 'livetalking',
      status: 'connecting',
      statusMessage: 'Connecting to LiveTalking',
    }));

    try {
      const client = new LiveTalkingClient(state.liveTalking);
      liveTalkingClientRef.current = client;
      const sessionId = await client.connect(setLiveTalkingStream);
      setState((current) => ({
        ...current,
        mode: 'livetalking',
        status: 'ready',
        statusMessage: `LiveTalking connected: ${sessionId}`,
      }));
    } catch (error) {
      const message = getErrorMessage(error);
      liveTalkingClientRef.current?.disconnect();
      liveTalkingClientRef.current = null;
      setLiveTalkingStream(null);
      setState((current) => ({
        ...current,
        mode: 'livetalking',
        status: 'error',
        statusMessage: `LiveTalking connection failed: ${message}`,
      }));
      toaster.create({
        title: `LiveTalking connection failed: ${message}`,
        type: 'error',
        duration: 3000,
      });
    }
  }, [state.liveTalking]);

  const consumeLiveTalkingAudio = useCallback(async (message: AvatarAudioMessage) => {
    if (!message.audio) {
      return;
    }

    if (!liveTalkingClientRef.current) {
      await connectLiveTalking();
    }

    const client = liveTalkingClientRef.current;
    if (!client) {
      throw new Error('LiveTalking client is not available');
    }

    setState((current) => ({
      ...current,
      status: 'speaking',
      statusMessage: 'Forwarding audio to LiveTalking',
    }));

    try {
      await client.sendAudio(message.audio);
      setState((current) => ({
        ...current,
        status: 'ready',
        statusMessage: 'LiveTalking ready',
      }));
    } catch (error) {
      const errorMessage = getErrorMessage(error);
      setState((current) => ({
        ...current,
        status: 'error',
        statusMessage: `LiveTalking audio forwarding failed: ${errorMessage}`,
      }));
      toaster.create({
        title: `LiveTalking audio forwarding failed: ${errorMessage}`,
        type: 'error',
        duration: 3000,
      });
    }
  }, [connectLiveTalking]);

  const interruptActiveRenderer = useCallback(async () => {
    if (state.mode !== 'livetalking') {
      return;
    }

    try {
      await liveTalkingClientRef.current?.interrupt();
      setState((current) => ({
        ...current,
        status: 'ready',
        statusMessage: 'LiveTalking interrupted',
      }));
    } catch (error) {
      const message = getErrorMessage(error);
      setState((current) => ({
        ...current,
        status: 'error',
        statusMessage: `LiveTalking interrupt failed: ${message}`,
      }));
      toaster.create({
        title: `LiveTalking interrupt failed: ${message}`,
        type: 'error',
        duration: 3000,
      });
    }
  }, [state.mode]);

  const value = useMemo<AvatarRendererContextValue>(() => ({
    ...state,
    liveTalkingStream,
    setMode,
    setLiveTalkingConfig,
    setUe5Config,
    connectLiveTalking,
    consumeLiveTalkingAudio,
    interruptActiveRenderer,
  }), [
    state,
    liveTalkingStream,
    setMode,
    setLiveTalkingConfig,
    setUe5Config,
    connectLiveTalking,
    consumeLiveTalkingAudio,
    interruptActiveRenderer,
  ]);

  return (
    <AvatarRendererContext.Provider value={value}>
      {children}
    </AvatarRendererContext.Provider>
  );
}

export function useAvatarRenderer() {
  const context = useContext(AvatarRendererContext);
  if (!context) {
    throw new Error('useAvatarRenderer must be used within AvatarRendererProvider');
  }
  return context;
}
```

- [ ] **Step 2: Wrap the app with the provider**

Modify imports in `frontend/src/renderer/src/App.tsx`:

```tsx
import { AvatarRendererProvider } from "./context/avatar-renderer-context";
```

Wrap the existing `WebSocketHandler` block:

```tsx
<AvatarRendererProvider>
  <WebSocketHandler>
    <Toaster />
    <AppContent />
  </WebSocketHandler>
</AvatarRendererProvider>
```

- [ ] **Step 3: Run typecheck**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS.

- [ ] **Step 4: Commit renderer context**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git add src/renderer/src/context/avatar-renderer-context.tsx src/renderer/src/App.tsx
git commit -m "Add avatar renderer state for the console" \
  -m "Renderer mode, LiveTalking connection state, and UE5 configuration need one context that can be shared by the stage, settings, message handler, and interrupt flow." \
  -m "Constraint: Avoid coupling the context to WebSocketProvider to prevent provider cycles" \
  -m "Confidence: high" \
  -m "Scope-risk: moderate" \
  -m "Tested: npm run typecheck:web"
```

## Task 5: Route Audio And Interrupts Through The Active Renderer

**Files:**
- Modify: `frontend/src/renderer/src/services/websocket-handler.tsx`
- Modify: `frontend/src/renderer/src/hooks/utils/use-interrupt.ts`

- [ ] **Step 1: Import renderer context in the WebSocket handler**

Add to `frontend/src/renderer/src/services/websocket-handler.tsx` imports:

```tsx
import { useAvatarRenderer } from '@/context/avatar-renderer-context';
```

Inside `WebSocketHandler`, after `const { setBrowserViewData } = useBrowser();`, add:

```tsx
const { mode: avatarMode, consumeLiveTalkingAudio } = useAvatarRenderer();
```

- [ ] **Step 2: Replace the `audio` case**

Replace the current `case 'audio':` block in `handleWebSocketMessage` with this final block:

```tsx
      case 'audio':
        if (aiState === 'interrupted' || aiState === 'listening') {
          console.log('Audio playback intercepted. Sentence:', message.display_text?.text);
        } else if (avatarMode === 'livetalking') {
          if (message.display_text) {
            addAudioTask({
              audioBase64: '',
              volumes: [],
              sliceLength: 0,
              displayText: message.display_text,
              expressions: null,
              forwarded: true,
            });
          }
          consumeLiveTalkingAudio(message).catch((error) => {
            console.error('LiveTalking audio forwarding failed:', error);
          });
        } else {
          console.log("actions", message.actions);
          addAudioTask({
            audioBase64: message.audio || '',
            volumes: message.volumes || [],
            sliceLength: message.slice_length || 0,
            displayText: message.display_text || null,
            expressions: message.actions?.expressions || null,
            forwarded: message.forwarded || false,
          });
        }
        break;
```

This uses the existing audio task path for subtitle/chat text while forwarding actual audio to LiveTalking.

- [ ] **Step 3: Update the hook dependency list**

Add `avatarMode` and `consumeLiveTalkingAudio` to the `useCallback` dependency array for `handleWebSocketMessage`.

Expected final dependency list contains:

```tsx
avatarMode,
consumeLiveTalkingAudio,
```

- [ ] **Step 4: Import renderer context in interrupt hook**

Add to `frontend/src/renderer/src/hooks/utils/use-interrupt.ts`:

```ts
import { useAvatarRenderer } from '@/context/avatar-renderer-context';
```

Inside `useInterrupt`, after `const { stopCurrentAudioAndLipSync } = useAudioTask();`, add:

```ts
const { interruptActiveRenderer } = useAvatarRenderer();
```

- [ ] **Step 5: Call active renderer interrupt**

In `interrupt`, after `stopCurrentAudioAndLipSync();`, add:

```ts
interruptActiveRenderer().catch((error) => {
  console.error('Renderer interrupt failed:', error);
});
```

- [ ] **Step 6: Run typecheck**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS.

- [ ] **Step 7: Commit routing changes**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git add src/renderer/src/services/websocket-handler.tsx src/renderer/src/hooks/utils/use-interrupt.ts
git commit -m "Route runtime audio through the selected avatar renderer" \
  -m "Live2D keeps the existing audio queue while LiveTalking receives generated WAV payloads through its WebRTC session. Interrupts now notify the active renderer before the backend signal is sent." \
  -m "Constraint: Preserve current Live2D behavior as the default path" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Tested: npm run typecheck:web"
```

## Task 6: Build The Digital-Human Stage

**Files:**
- Create: `frontend/src/renderer/src/components/console/digital-human-stage.tsx`
- Modify: `frontend/src/renderer/src/components/canvas/live2d.tsx`

- [ ] **Step 1: Allow Live2D to render in a bounded stage**

Modify `Live2DProps` in `frontend/src/renderer/src/components/canvas/live2d.tsx`:

```tsx
interface Live2DProps {
  showSidebar?: boolean;
  stageMode?: boolean;
}
```

Modify the component signature:

```tsx
({ showSidebar, stageMode = false }: Live2DProps): JSX.Element => {
```

Modify `isPet`:

```tsx
const isPet = mode === 'pet' && !stageMode;
```

- [ ] **Step 2: Create the stage component**

Create `frontend/src/renderer/src/components/console/digital-human-stage.tsx`:

```tsx
import { Box, Button, HStack, Input, Text, VStack } from '@chakra-ui/react';
import { useEffect, useRef } from 'react';
import { Live2D } from '@/components/canvas/live2d';
import { useAvatarRenderer } from '@/context/avatar-renderer-context';
import { AvatarRendererMode } from '@/types/avatar-renderer';

const rendererModes: Array<{ mode: AvatarRendererMode; label: string }> = [
  { mode: 'live2d', label: 'Live2D' },
  { mode: 'livetalking', label: 'LiveTalking' },
  { mode: 'ue5', label: 'UE5' },
];

function LiveTalkingVideo() {
  const { liveTalkingStream } = useAvatarRenderer();
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = liveTalkingStream;
    }
  }, [liveTalkingStream]);

  return (
    <video
      ref={videoRef}
      autoPlay
      playsInline
      controls={false}
      style={{
        width: '100%',
        height: '100%',
        objectFit: 'cover',
        background: '#111827',
      }}
    />
  );
}

export function DigitalHumanStage() {
  const {
    mode,
    status,
    statusMessage,
    ue5,
    setMode,
    setUe5Config,
    connectLiveTalking,
  } = useAvatarRenderer();

  return (
    <Box
      h="100%"
      minH="0"
      bg="white"
      border="1px solid"
      borderColor="gray.200"
      borderRadius="8px"
      overflow="hidden"
      display="flex"
      flexDirection="column"
    >
      <HStack justify="space-between" px="4" py="3" borderBottom="1px solid" borderColor="gray.100">
        <HStack gap="2">
          {rendererModes.map((item) => (
            <Button
              key={item.mode}
              size="sm"
              variant={mode === item.mode ? 'solid' : 'outline'}
              colorPalette={mode === item.mode ? 'teal' : 'gray'}
              onClick={() => setMode(item.mode)}
            >
              {item.label}
            </Button>
          ))}
        </HStack>
        <Text fontSize="xs" color={status === 'error' ? 'red.600' : 'gray.600'}>
          {status} · {statusMessage}
        </Text>
      </HStack>

      <Box flex="1" minH="0" bg="gray.50" position="relative">
        {mode === 'live2d' && <Live2D stageMode />}

        {mode === 'livetalking' && (
          <VStack h="100%" gap="0">
            <Box flex="1" w="100%" minH="0">
              <LiveTalkingVideo />
            </Box>
            <HStack w="100%" p="3" borderTop="1px solid" borderColor="gray.200" bg="white">
              <Button size="sm" colorPalette="teal" onClick={connectLiveTalking}>
                连接 LiveTalking
              </Button>
              <Text fontSize="sm" color="gray.600">
                http://localhost:8010 · wav2lip256_avatar1
              </Text>
            </HStack>
          </VStack>
        )}

        {mode === 'ue5' && (
          <VStack h="100%" justify="center" p="6" gap="4">
            <Text fontWeight="semibold" color="gray.700">
              待连接 Pixel Streaming
            </Text>
            <Input
              value={ue5.pixelStreamingUrl}
              onChange={(event) => setUe5Config({ pixelStreamingUrl: event.target.value })}
              placeholder="http://localhost:80"
              maxW="420px"
              bg="white"
            />
            {ue5.pixelStreamingUrl && (
              <Box as="iframe" src={ue5.pixelStreamingUrl} title="UE5 Pixel Streaming" w="100%" h="70%" border="0" />
            )}
          </VStack>
        )}
      </Box>
    </Box>
  );
}
```

- [ ] **Step 3: Run typecheck**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS.

- [ ] **Step 4: Commit digital-human stage**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git add src/renderer/src/components/console/digital-human-stage.tsx src/renderer/src/components/canvas/live2d.tsx
git commit -m "Add the digital-human stage to the runtime console" \
  -m "The chat console needs a bounded stage that can host Live2D, LiveTalking video, and a visible UE5 Pixel Streaming placeholder without changing backend protocol." \
  -m "Constraint: Live2D must still work inside the existing pet/window modes" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Tested: npm run typecheck:web"
```

## Task 7: Build Console Shell, Sidebar, And Chat Panel

**Files:**
- Modify: `frontend/src/renderer/src/hooks/footer/use-footer.ts`
- Create: `frontend/src/renderer/src/components/console/status-bar.tsx`
- Create: `frontend/src/renderer/src/components/console/session-sidebar.tsx`
- Create: `frontend/src/renderer/src/components/console/chat-console.tsx`
- Create: `frontend/src/renderer/src/components/console/console-shell.tsx`

- [ ] **Step 1: Expose send handler from the existing footer hook**

Modify `frontend/src/renderer/src/hooks/footer/use-footer.ts`.

In the destructuring from `useTextInput`, add `handleSend`:

```ts
  const {
    inputText: inputValue,
    setInputText: handleChange,
    handleSend,
    handleKeyPress: handleKey,
    handleCompositionStart,
    handleCompositionEnd,
  } = useTextInput();
```

In the returned object, add:

```ts
    handleSend,
```

- [ ] **Step 2: Create status bar**

Create `frontend/src/renderer/src/components/console/status-bar.tsx`:

```tsx
import { Badge, Box, Button, HStack, Text } from '@chakra-ui/react';
import { FiRefreshCw, FiSettings } from 'react-icons/fi';
import { useAvatarRenderer } from '@/context/avatar-renderer-context';
import { useWebSocket } from '@/context/websocket-context';

export function StatusBar({ onSettingsOpen }: { onSettingsOpen: () => void }) {
  const { wsState, reconnect } = useWebSocket();
  const { mode, status } = useAvatarRenderer();
  const isOnline = wsState === 'OPEN';

  return (
    <HStack h="64px" px="5" bg="white" borderBottom="1px solid" borderColor="gray.200" justify="space-between">
      <Box>
        <Text fontSize="md" fontWeight="semibold" color="gray.900">
          Open-LLM-VTuber
        </Text>
        <Text fontSize="xs" color="gray.500">
          运行时控制台
        </Text>
      </Box>
      <HStack gap="2">
        <Badge colorPalette={isOnline ? 'green' : 'red'}>{wsState}</Badge>
        <Badge colorPalette={status === 'error' ? 'red' : 'teal'}>{mode}</Badge>
        <Button size="sm" variant="outline" onClick={reconnect}>
          <FiRefreshCw /> 刷新
        </Button>
        <Button size="sm" variant="outline" onClick={onSettingsOpen}>
          <FiSettings /> 设置
        </Button>
      </HStack>
    </HStack>
  );
}
```

- [ ] **Step 3: Create session sidebar**

Create `frontend/src/renderer/src/components/console/session-sidebar.tsx`:

```tsx
import { Badge, Box, Button, HStack, Text, VStack } from '@chakra-ui/react';
import { FiPlus, FiSettings } from 'react-icons/fi';
import { useChatHistory } from '@/context/chat-history-context';
import { useConfig } from '@/context/character-config-context';
import { useWebSocket } from '@/context/websocket-context';

export function SessionSidebar({ onSettingsOpen }: { onSettingsOpen: () => void }) {
  const { historyList, currentHistoryUid } = useChatHistory();
  const { confName } = useConfig();
  const { sendMessage, wsState } = useWebSocket();

  return (
    <Box h="100%" bg="white" borderRight="1px solid" borderColor="gray.200" display="flex" flexDirection="column">
      <VStack align="stretch" gap="3" p="4" borderBottom="1px solid" borderColor="gray.100">
        <HStack justify="space-between">
          <Text fontSize="sm" fontWeight="semibold" color="gray.800">会话</Text>
          <Badge colorPalette={wsState === 'OPEN' ? 'green' : 'red'}>{wsState}</Badge>
        </HStack>
        <Text fontSize="xs" color="gray.500">当前角色：{confName || '未加载'}</Text>
        <Button size="sm" colorPalette="teal" onClick={() => sendMessage({ type: 'create-new-history' })}>
          <FiPlus /> 新建会话
        </Button>
        <Button size="sm" variant="outline" onClick={onSettingsOpen}>
          <FiSettings /> 数字人设置
        </Button>
      </VStack>

      <VStack align="stretch" gap="2" p="3" overflowY="auto" flex="1">
        {historyList.map((history) => (
          <Box
            key={history.uid}
            p="3"
            borderRadius="6px"
            border="1px solid"
            borderColor={history.uid === currentHistoryUid ? 'teal.200' : 'gray.200'}
            bg={history.uid === currentHistoryUid ? 'teal.50' : 'white'}
          >
            <Text fontSize="sm" fontWeight="medium" color="gray.800" truncate>
              {history.latest_message?.content || '新会话'}
            </Text>
            <Text fontSize="xs" color="gray.500" mt="1">
              {history.timestamp || '刚刚'}
            </Text>
          </Box>
        ))}
      </VStack>
    </Box>
  );
}
```

- [ ] **Step 4: Create chat console**

Create `frontend/src/renderer/src/components/console/chat-console.tsx`:

```tsx
import { Badge, Box, Button, HStack, IconButton, Text, Textarea, VStack } from '@chakra-ui/react';
import { BsMicFill, BsMicMuteFill } from 'react-icons/bs';
import { IoHandRightSharp, IoSend } from 'react-icons/io5';
import { useChatHistory } from '@/context/chat-history-context';
import { useFooter } from '@/hooks/footer/use-footer';
import AIStateIndicator from '@/components/footer/ai-state-indicator';

export function ChatConsole() {
  const { messages } = useChatHistory();
  const {
    inputValue,
    handleInputChange,
    handleKeyPress,
    handleCompositionStart,
    handleCompositionEnd,
    handleSend,
    handleInterrupt,
    handleMicToggle,
    micOn,
  } = useFooter();

  return (
    <Box h="100%" bg="white" border="1px solid" borderColor="gray.200" borderRadius="8px" display="flex" flexDirection="column" overflow="hidden">
      <HStack justify="space-between" px="4" py="3" borderBottom="1px solid" borderColor="gray.100">
        <Box>
          <Text fontSize="sm" fontWeight="semibold" color="gray.900">当前会话</Text>
          <HStack mt="1" gap="2">
            <AIStateIndicator />
            <Badge colorPalette="gray">request_id 自动生成</Badge>
          </HStack>
        </Box>
        <Button colorPalette="orange" size="sm" onClick={handleInterrupt}>
          <IoHandRightSharp /> 打断播报
        </Button>
      </HStack>

      <VStack align="stretch" flex="1" minH="0" overflowY="auto" p="4" gap="3" bg="gray.50">
        {messages.length === 0 ? (
          <Text color="gray.500" fontSize="sm" textAlign="center" mt="12">
            输入问题或开启语音，与数字人开始对话。
          </Text>
        ) : messages.map((message) => (
          <Box key={message.id} alignSelf={message.role === 'human' ? 'flex-end' : 'flex-start'} maxW="78%">
            <Box
              px="4"
              py="3"
              borderRadius="8px"
              bg={message.role === 'human' ? 'teal.600' : 'white'}
              color={message.role === 'human' ? 'white' : 'gray.800'}
              border="1px solid"
              borderColor={message.role === 'human' ? 'teal.600' : 'gray.200'}
            >
              <Text fontSize="sm" whiteSpace="pre-wrap">{message.content}</Text>
              {message.type === 'tool_call_status' && (
                <Badge mt="2" colorPalette={message.status === 'error' ? 'red' : 'blue'}>
                  {message.tool_name} · {message.status}
                </Badge>
              )}
            </Box>
          </Box>
        ))}
      </VStack>

      <Box p="3" borderTop="1px solid" borderColor="gray.100">
        <Textarea
          value={inputValue}
          onChange={handleInputChange}
          onKeyDown={handleKeyPress}
          onCompositionStart={handleCompositionStart}
          onCompositionEnd={handleCompositionEnd}
          placeholder="输入要让数字人回答的问题"
          minH="78px"
          resize="none"
          bg="white"
        />
        <HStack justify="space-between" mt="3">
          <IconButton aria-label="语音输入" colorPalette={micOn ? 'green' : 'red'} onClick={handleMicToggle}>
            {micOn ? <BsMicFill /> : <BsMicMuteFill />}
          </IconButton>
          <HStack>
            <Button variant="outline" colorPalette="orange" onClick={handleInterrupt}>
              <IoHandRightSharp /> 打断
            </Button>
            <Button colorPalette="teal" onClick={handleSend}>
              <IoSend /> 发送
            </Button>
          </HStack>
        </HStack>
      </Box>
    </Box>
  );
}
```

- [ ] **Step 5: Create console shell**

Create `frontend/src/renderer/src/components/console/console-shell.tsx`:

```tsx
import { Box, Grid } from '@chakra-ui/react';
import { useState } from 'react';
import { ChatConsole } from './chat-console';
import { DigitalHumanStage } from './digital-human-stage';
import { SessionSidebar } from './session-sidebar';
import { StatusBar } from './status-bar';
import { DigitalHumanSettings } from './digital-human-settings';

export function ConsoleShell() {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <Box h="100vh" bg="gray.100" color="gray.900" overflow="hidden">
      <StatusBar onSettingsOpen={() => setSettingsOpen(true)} />
      <Grid templateColumns="300px minmax(420px, 1fr) minmax(360px, 42vw)" gap="4" h="calc(100vh - 64px)" p="4">
        <SessionSidebar onSettingsOpen={() => setSettingsOpen(true)} />
        <ChatConsole />
        <DigitalHumanStage />
      </Grid>
      <DigitalHumanSettings open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </Box>
  );
}
```

This shell imports `DigitalHumanSettings`, which is created in Task 8. Run the Task 7 typecheck after completing Task 8.

## Task 8: Add Digital-Human Settings Panel

**Files:**
- Create: `frontend/src/renderer/src/components/console/digital-human-settings.tsx`

- [ ] **Step 1: Create settings panel**

Create `frontend/src/renderer/src/components/console/digital-human-settings.tsx`:

```tsx
import {
  Box,
  Button,
  HStack,
  Input,
  Text,
  VStack,
} from '@chakra-ui/react';
import { useState } from 'react';
import { useAvatarRenderer } from '@/context/avatar-renderer-context';
import {
  DrawerBackdrop,
  DrawerBody,
  DrawerContent,
  DrawerFooter,
  DrawerHeader,
  DrawerRoot,
  DrawerTitle,
} from '@/components/ui/drawer';
import { Switch } from '@/components/ui/switch';

export function DigitalHumanSettings({ open, onClose }: { open: boolean; onClose: () => void }) {
  const {
    liveTalking,
    ue5,
    setLiveTalkingConfig,
    setUe5Config,
    connectLiveTalking,
  } = useAvatarRenderer();
  const [serviceUrl, setServiceUrl] = useState(liveTalking.serviceUrl);
  const [avatarId, setAvatarId] = useState(liveTalking.avatarId);
  const [useStun, setUseStun] = useState(liveTalking.useStun);
  const [pixelStreamingUrl, setPixelStreamingUrl] = useState(ue5.pixelStreamingUrl);

  const save = () => {
    setLiveTalkingConfig({ serviceUrl, avatarId, useStun });
    setUe5Config({ pixelStreamingUrl });
    onClose();
  };

  return (
    <DrawerRoot open={open} onOpenChange={(event) => !event.open && onClose()} placement="end">
      <DrawerBackdrop />
      <DrawerContent>
        <DrawerHeader>
          <DrawerTitle>数字人设置</DrawerTitle>
        </DrawerHeader>
        <DrawerBody>
          <VStack align="stretch" gap="5">
            <Box>
              <Text fontWeight="semibold" mb="2">Live2D</Text>
              <Text fontSize="sm" color="gray.600">模型选择沿用现有角色配置和 set-model-and-conf 流程。</Text>
            </Box>

            <Box>
              <Text fontWeight="semibold" mb="2">LiveTalking</Text>
              <VStack align="stretch" gap="3">
                <Input value={serviceUrl} onChange={(event) => setServiceUrl(event.target.value)} placeholder="http://localhost:8010" />
                <Input value={avatarId} onChange={(event) => setAvatarId(event.target.value)} placeholder="wav2lip256_avatar1" />
                <HStack justify="space-between">
                  <Text fontSize="sm">使用 STUN</Text>
                  <Switch checked={useStun} onCheckedChange={(event) => setUseStun(Boolean(event.checked))} />
                </HStack>
                <Button colorPalette="teal" onClick={connectLiveTalking}>测试连接</Button>
              </VStack>
            </Box>

            <Box>
              <Text fontWeight="semibold" mb="2">UE5 Pixel Streaming</Text>
              <Input value={pixelStreamingUrl} onChange={(event) => setPixelStreamingUrl(event.target.value)} placeholder="http://localhost:80" />
            </Box>
          </VStack>
        </DrawerBody>
        <DrawerFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button colorPalette="teal" onClick={save}>保存</Button>
        </DrawerFooter>
      </DrawerContent>
    </DrawerRoot>
  );
}
```

- [ ] **Step 2: Run typecheck for Tasks 7 and 8 together**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS.

- [ ] **Step 3: Commit console UI**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git add src/renderer/src/components/console src/renderer/src/hooks/footer/use-footer.ts
git commit -m "Build the smart-human runtime console UI" \
  -m "The runtime page now has a status bar, session sidebar, chat console, digital-human stage, and compact renderer settings surface matching the agreed phase-one scope." \
  -m "Constraint: Do not add a full operations backend in phase one" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Tested: npm run typecheck:web"
```

## Task 9: Replace The Window Layout With ConsoleShell

**Files:**
- Modify: `frontend/src/renderer/src/App.tsx`
- Modify: `frontend/src/renderer/src/layout.tsx`

- [ ] **Step 1: Import ConsoleShell**

Add to `frontend/src/renderer/src/App.tsx`:

```tsx
import { ConsoleShell } from "./components/console/console-shell";
```

- [ ] **Step 2: Replace window-mode rendering**

In `AppContent`, keep pet mode behavior but replace the `mode === "window"` block with:

```tsx
      {mode === "window" && (
        <>
          {isElectron && <TitleBar />}
          <Box mt={isElectron ? "30px" : "0"} h={isElectron ? "calc(100vh - 30px)" : "100vh"}>
            <ConsoleShell />
          </Box>
        </>
      )}
```

Keep this pet-mode block unchanged:

```tsx
      {mode === "pet" && <InputSubtitle />}
```

- [ ] **Step 3: Remove the old absolute Live2D overlay for window mode**

In `AppContent`, render the old full-screen Live2D container only for pet mode:

```tsx
      {mode === "pet" && (
        <Box ref={live2dContainerRef} {...live2dPetStyle}>
          <Live2D />
        </Box>
      )}
```

Delete the old unconditional `<Box ref={live2dContainerRef}>` that wrapped `<Live2D />`.

- [ ] **Step 4: Remove unused imports**

From `frontend/src/renderer/src/App.tsx`, remove imports that become unused after replacing the layout:

```tsx
import Sidebar from "./components/sidebar/sidebar";
import Footer from "./components/footer/footer";
import { layoutStyles } from "./layout";
import Background from "./components/canvas/background";
import WebSocketStatus from "./components/canvas/ws-status";
import Subtitle from "./components/canvas/subtitle";
```

Keep `Live2D`, `TitleBar`, `InputSubtitle`, providers, and `ConsoleShell`.

- [ ] **Step 5: Run typecheck**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS.

- [ ] **Step 6: Commit layout replacement**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git add src/renderer/src/App.tsx src/renderer/src/layout.tsx
git commit -m "Make the console shell the default runtime layout" \
  -m "The window runtime now opens into the smart-human console while pet mode keeps the prior overlay path. Live2D is hosted by the stage instead of a full-screen window overlay." \
  -m "Constraint: Preserve desktop pet mode behavior" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Tested: npm run typecheck:web"
```

## Task 10: Add Console Translations

**Files:**
- Modify: `frontend/src/renderer/src/locales/en/translation.json`
- Modify: `frontend/src/renderer/src/locales/zh/translation.json`

- [ ] **Step 1: Add English strings**

In `frontend/src/renderer/src/locales/en/translation.json`, add this top-level key near existing feature keys:

```json
"console": {
  "title": "Open-LLM-VTuber",
  "subtitle": "Runtime Console",
  "session": "Session",
  "newSession": "New Session",
  "digitalHumanSettings": "Digital Human Settings",
  "currentConversation": "Current Conversation",
  "emptyConversation": "Enter a question or start voice input to talk with the digital human.",
  "inputPlaceholder": "Enter a question for the digital human",
  "interrupt": "Interrupt",
  "send": "Send",
  "liveTalkingConnect": "Connect LiveTalking",
  "ue5Pending": "Waiting for Pixel Streaming"
}
```

- [ ] **Step 2: Add Chinese strings**

In `frontend/src/renderer/src/locales/zh/translation.json`, add this top-level key near existing feature keys:

```json
"console": {
  "title": "Open-LLM-VTuber",
  "subtitle": "运行时控制台",
  "session": "会话",
  "newSession": "新建会话",
  "digitalHumanSettings": "数字人设置",
  "currentConversation": "当前会话",
  "emptyConversation": "输入问题或开启语音，与数字人开始对话。",
  "inputPlaceholder": "输入要让数字人回答的问题",
  "interrupt": "打断",
  "send": "发送",
  "liveTalkingConnect": "连接 LiveTalking",
  "ue5Pending": "待连接 Pixel Streaming"
}
```

- [ ] **Step 3: Replace hardcoded console labels**

Replace hardcoded labels in the new `frontend/src/renderer/src/components/console/*.tsx` files with `useTranslation()` and the `console.*` keys where practical. Keep protocol names such as `Live2D`, `LiveTalking`, and `UE5` hardcoded.

Example in `status-bar.tsx`:

```tsx
const { t } = useTranslation();
...
{t('console.title')}
{t('console.subtitle')}
```

- [ ] **Step 4: Run typecheck**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS.

- [ ] **Step 5: Commit translations**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git add src/renderer/src/locales/en/translation.json src/renderer/src/locales/zh/translation.json src/renderer/src/components/console
git commit -m "Localize the runtime console copy" \
  -m "Console labels are added to the existing i18n files so the redesigned runtime remains bilingual like the current frontend." \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Tested: npm run typecheck:web"
```

## Task 11: Verify Build And Manual Runtime Paths

**Files:**
- Read: `frontend/package.json`
- Read: `doc/livetalking-integration.md`

- [ ] **Step 1: Run web typecheck**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run typecheck:web
```

Expected: PASS.

- [ ] **Step 2: Run web build**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run build:web
```

Expected: PASS.

- [ ] **Step 3: Start frontend dev server**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run dev:web -- --host 0.0.0.0
```

Expected: Vite prints a local URL, usually `http://localhost:5173/`.

- [ ] **Step 4: Start Open-LLM-VTuber backend in another shell**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber
uv run run_server.py
```

Expected: backend serves WebSocket at `ws://127.0.0.1:12393/client-ws`.

- [ ] **Step 5: Start LiveTalking in another shell**

Run:

```bash
cd /mnt/d/AI/LiveTalking
python app.py --transport webrtc --model wav2lip --avatar_id wav2lip256_avatar1
```

Expected: LiveTalking serves `http://localhost:8010/offer`.

- [ ] **Step 6: Manual check Live2D**

Open the Vite URL and verify:

```text
Renderer mode: Live2D
Expected: model appears in the digital-human stage
Expected: text input sends a message
Expected: AI answer appears in chat
Expected: audio playback and Live2D expression behavior match the old frontend
Expected: 打断播报 stops the current playback path
```

- [ ] **Step 7: Manual check LiveTalking**

Switch to LiveTalking and verify:

```text
Click: 连接 LiveTalking
Expected: status becomes ready
Expected: video stream appears in the stage
Send: a text question
Expected: answer appears in chat
Expected: generated audio is POSTed to /humanaudio
Expected: LiveTalking avatar speaks from the WebRTC stream
Click: 打断播报
Expected: frontend sends backend interrupt-signal and calls /interrupt_talk
```

- [ ] **Step 8: Manual check UE5 placeholder**

Switch to UE5 and verify:

```text
Expected: stage says 待连接 Pixel Streaming
Input: http://localhost:80
Expected: iframe preview area appears
Expected: UI does not claim UE5 is online unless the URL is configured
```

- [ ] **Step 9: Commit verification notes if documentation changed**

If verification reveals required run instructions, update `doc/livetalking-integration.md` or create a short frontend note. Commit only if a doc file changed:

```bash
cd /mnt/d/AI/Open-LLM-VTuber
git add doc/livetalking-integration.md
git commit -m "Document runtime console LiveTalking verification" \
  -m "Manual verification details are recorded after wiring the console to LiveTalking so future runs can reproduce the local setup." \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Tested: npm run typecheck:web; npm run build:web; manual LiveTalking smoke test"
```

## Task 12: Publish Build Output Through The Existing Frontend Delivery Path

**Files:**
- Modify: `frontend` submodule build branch or deployment output, depending on the existing `Open-LLM-VTuber-Web` release workflow.
- Modify: parent repo submodule pointer after build output is committed.

- [ ] **Step 1: Confirm web build output path**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
npm run build:web
find . -maxdepth 3 -type d \( -name dist -o -name out -o -name renderer \) | sort
```

Expected: locate the web static output generated by Vite.

- [ ] **Step 2: Inspect the Web repo for an existing build publish script**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
rg -n "gh-pages|deploy|build branch|build-branch|dist|out/renderer" package.json README.md .github electron.vite.config.ts vite.config.ts
```

Expected: identify the command or CI path that publishes web build output to the `build` branch. Record the exact command in the implementation handoff.

- [ ] **Step 3: Stop before manual publish if no publish path exists**

Run:

```bash
cd /mnt/d/AI/Open-LLM-VTuber/frontend
git status --short
```

Expected: the source branch is clean. If Step 2 does not reveal a documented publish command, stop here and report: `Build passed, but Web repo build-branch publish workflow was not found.` Do not invent a manual build-branch rewrite in this plan.

- [ ] **Step 4: Update parent submodule pointer after the build branch is published**

After the Web submodule build output is published to the submodule delivery branch, update the parent repo pointer:

```bash
cd /mnt/d/AI/Open-LLM-VTuber
git status --short frontend
git add frontend
git commit -m "Point the frontend submodule at the runtime console build" \
  -m "The parent project serves the frontend submodule as static assets, so the submodule pointer must advance after publishing the redesigned runtime console build." \
  -m "Constraint: Main backend mounts frontend as static files" \
  -m "Confidence: medium" \
  -m "Scope-risk: moderate" \
  -m "Tested: npm run typecheck:web; npm run build:web; manual console smoke test"
```

Expected: parent repo records only the `frontend` submodule pointer change unless documentation was intentionally updated.

## Self-Review

Spec coverage:

- Runtime console scope is covered by Tasks 7 and 9.
- Digital-human stage is covered by Task 6.
- Live2D preservation is covered by Tasks 5, 6, and 9.
- LiveTalking WebRTC, `/humanaudio`, and interrupt are covered by Tasks 3, 4, 5, 6, and 11.
- UE5 Pixel Streaming placeholder is covered by Tasks 6, 8, and 11.
- Settings drawer/panel is covered by Task 8.
- Source-branch workflow is covered by Tasks 1 and 12.
- Verification is covered by Task 11.

Placeholder scan:

- The only placeholder references are intentional UE5 phase-one placeholder behavior.
- No TBD/TODO/fill-in instructions remain.

Type consistency:

- Renderer mode type is `AvatarRendererMode`.
- LiveTalking config is `LiveTalkingConfig`.
- Context hook is `useAvatarRenderer`.
- Audio message type is `AvatarAudioMessage`, aliased from existing `AudioPayload`.
