import type { LiveTalkingConfig, OfferResponse } from "./types";

export class LiveTalkingClient {
  private peerConnection: RTCPeerConnection | null = null;
  private sessionId: string | null = null;
  private audioAbortController: AbortController | null = null;
  private audioSocket: WebSocket | null = null;
  private audioSocketConnecting: Promise<void> | null = null;
  private pendingAudioAcks: AudioAckHandler[] = [];

  constructor(private readonly config: LiveTalkingConfig) {}

  getSessionId() {
    return this.sessionId;
  }

  async getStats() {
    return this.peerConnection?.getStats() ?? null;
  }

  async connect(onStream: (stream: MediaStream) => void) {
    this.disconnect();

    const rtcConfig: RTCConfiguration = {};
    if (this.config.useStun) {
      rtcConfig.iceServers = [{ urls: ["stun:stun.l.google.com:19302"] }];
    }

    const peerConnection = new RTCPeerConnection(rtcConfig);
    this.peerConnection = peerConnection;

    peerConnection.addTransceiver("video", { direction: "recvonly" });
    peerConnection.addTransceiver("audio", { direction: "recvonly" });
    peerConnection.addEventListener("track", (event) => {
      const [stream] = event.streams;
      if (stream) {
        onStream(stream);
      }
    });

    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);
    await waitForIceGatheringComplete(peerConnection);

    const response = await fetch(`${this.config.serviceUrl}/offer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sdp: peerConnection.localDescription?.sdp,
        type: peerConnection.localDescription?.type,
        avatar: this.config.avatarId,
        use_stun: this.config.useStun,
      }),
    });

    const answer = await parseLiveTalkingResponse<OfferResponse>(
      response,
      "/offer",
    );

    if (!answer.sdp || !answer.type || !answer.sessionid) {
      throw new Error("LiveTalking /offer returned an incomplete answer");
    }

    await peerConnection.setRemoteDescription({
      sdp: answer.sdp,
      type: answer.type,
    });
    this.sessionId = answer.sessionid;
    this.connectAudioSocket().catch(() => {
      // HTTP /humanaudio remains the fallback when this LiveTalking build
      // does not expose the WebSocket audio path yet.
    });
    return answer.sessionid;
  }

  async sendAudio(audioBase64: string) {
    if (!this.sessionId) {
      throw new Error("LiveTalking session is not connected");
    }

    const audioBytes = base64WavToBytes(audioBase64);

    try {
      await this.sendAudioOverWebSocket(audioBytes);
      return;
    } catch (error) {
      if (!(error instanceof WebSocketUnavailableError)) {
        throw error;
      }
    }

    await this.sendAudioOverHttp(audioBytes);
  }

  private async sendAudioOverWebSocket(audioBytes: Uint8Array) {
    try {
      await this.connectAudioSocket();
    } catch (error) {
      throw new WebSocketUnavailableError(
        error instanceof Error ? error.message : String(error),
      );
    }

    const socket = this.audioSocket;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      throw new WebSocketUnavailableError("audio WebSocket is not open");
    }

    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        removePending();
        reject(new Error("LiveTalking audio WebSocket ack timed out"));
      }, 5000);

      const handler: AudioAckHandler = {
        resolve: () => {
          window.clearTimeout(timeout);
          resolve();
        },
        reject: (error) => {
          window.clearTimeout(timeout);
          reject(error);
        },
      };

      const removePending = () => {
        const index = this.pendingAudioAcks.indexOf(handler);
        if (index >= 0) {
          this.pendingAudioAcks.splice(index, 1);
        }
      };

      this.pendingAudioAcks.push(handler);
      try {
        socket.send(audioBytes);
      } catch (error) {
        removePending();
        reject(
          new WebSocketUnavailableError(
            error instanceof Error ? error.message : String(error),
          ),
        );
      }
    });
  }

  private async sendAudioOverHttp(audioBytes: Uint8Array) {
    if (!this.sessionId) {
      throw new Error("LiveTalking session is not connected");
    }

    const formData = new FormData();
    formData.append("sessionid", this.sessionId);
    formData.append("file", wavBytesToBlob(audioBytes), "reply.wav");

    this.audioAbortController?.abort();
    const abortController = new AbortController();
    this.audioAbortController = abortController;

    try {
      const response = await fetch(`${this.config.serviceUrl}/humanaudio`, {
        method: "POST",
        body: formData,
        signal: abortController.signal,
      });
      await parseLiveTalkingResponse(response, "/humanaudio");
    } finally {
      if (this.audioAbortController === abortController) {
        this.audioAbortController = null;
      }
    }
  }

  async interrupt() {
    if (!this.sessionId) {
      return;
    }

    this.audioAbortController?.abort();
    this.audioAbortController = null;

    const jsonResponse = await fetch(`${this.config.serviceUrl}/interrupt_talk`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionid: this.sessionId }),
    });

    try {
      await parseLiveTalkingResponse(jsonResponse, "/interrupt_talk");
      return;
    } catch {
      // Some LiveTalking forks accept interrupt_talk only as multipart form data.
    }

    const formData = new FormData();
    formData.append("sessionid", this.sessionId);
    const formResponse = await fetch(`${this.config.serviceUrl}/interrupt_talk`, {
      method: "POST",
      body: formData,
    });
    await parseLiveTalkingResponse(formResponse, "/interrupt_talk");
  }

  disconnect() {
    this.closeAudioSocket();
    this.audioAbortController?.abort();
    this.audioAbortController = null;
    if (this.peerConnection) {
      this.peerConnection.getSenders().forEach((sender) => sender.track?.stop());
      this.peerConnection
        .getReceivers()
        .forEach((receiver) => receiver.track?.stop());
      this.peerConnection.close();
      this.peerConnection = null;
    }
    this.sessionId = null;
  }

  private async connectAudioSocket() {
    if (!this.sessionId) {
      throw new Error("LiveTalking session is not connected");
    }

    if (this.audioSocket?.readyState === WebSocket.OPEN) {
      return;
    }

    if (this.audioSocketConnecting) {
      await this.audioSocketConnecting;
      return;
    }

    this.closeAudioSocket();
    this.audioSocketConnecting = new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(
        buildAudioWebSocketUrl(this.config.serviceUrl, this.sessionId ?? ""),
      );
      const timeout = window.setTimeout(() => {
        socket.close();
        reject(new Error("LiveTalking audio WebSocket connection timed out"));
      }, 3000);

      socket.addEventListener("open", () => {
        window.clearTimeout(timeout);
        this.audioSocket = socket;
        resolve();
      });

      socket.addEventListener("message", (event) => {
        this.handleAudioSocketMessage(event);
      });

      socket.addEventListener("error", () => {
        window.clearTimeout(timeout);
        reject(new Error("LiveTalking audio WebSocket failed"));
      });

      socket.addEventListener("close", () => {
        window.clearTimeout(timeout);
        if (this.audioSocket === socket) {
          this.audioSocket = null;
        }
        this.rejectPendingAudioAcks(
          new WebSocketUnavailableError("LiveTalking audio WebSocket closed"),
        );
      });
    }).finally(() => {
      this.audioSocketConnecting = null;
    });

    await this.audioSocketConnecting;
  }

  private handleAudioSocketMessage(event: MessageEvent) {
    const handler = this.pendingAudioAcks.shift();
    if (!handler) {
      return;
    }

    try {
      const payload = JSON.parse(String(event.data)) as {
        code?: number;
        msg?: string;
      };
      if (typeof payload.code === "number" && payload.code !== 0) {
        handler.reject(
          new Error(`LiveTalking audio WebSocket failed: ${payload.msg ?? payload.code}`),
        );
        return;
      }
      handler.resolve();
    } catch (error) {
      handler.reject(
        error instanceof Error
          ? error
          : new Error("Invalid LiveTalking audio WebSocket ack"),
      );
    }
  }

  private rejectPendingAudioAcks(error: Error) {
    const pending = this.pendingAudioAcks.splice(0);
    pending.forEach((handler) => handler.reject(error));
  }

  private closeAudioSocket() {
    const socket = this.audioSocket;
    this.audioSocket = null;
    this.audioSocketConnecting = null;
    this.rejectPendingAudioAcks(
      new WebSocketUnavailableError("LiveTalking audio WebSocket closed"),
    );
    if (socket && socket.readyState !== WebSocket.CLOSED) {
      socket.close();
    }
  }
}

interface AudioAckHandler {
  resolve: () => void;
  reject: (error: Error) => void;
}

class WebSocketUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WebSocketUnavailableError";
  }
}

function base64WavToBytes(base64: string) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function wavBytesToBlob(bytes: Uint8Array) {
  return new Blob([bytes], { type: "audio/wav" });
}

function buildAudioWebSocketUrl(serviceUrl: string, sessionId: string) {
  const url = new URL(`${serviceUrl}/audio_ws`, window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("sessionid", sessionId);
  return url.toString();
}

async function waitForIceGatheringComplete(peerConnection: RTCPeerConnection) {
  if (peerConnection.iceGatheringState === "complete") {
    return;
  }

  await new Promise<void>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      peerConnection.removeEventListener(
        "icegatheringstatechange",
        handleStateChange,
      );
      reject(new Error("LiveTalking ICE gathering timed out"));
    }, 10000);

    function finish() {
      window.clearTimeout(timeout);
      peerConnection.removeEventListener(
        "icegatheringstatechange",
        handleStateChange,
      );
      resolve();
    }

    function handleStateChange() {
      if (peerConnection.iceGatheringState === "complete") {
        finish();
      }
    }

    peerConnection.addEventListener(
      "icegatheringstatechange",
      handleStateChange,
    );
    handleStateChange();
  });
}

async function parseLiveTalkingResponse<T extends { code?: number; msg?: string }>(
  response: Response,
  endpoint: string,
): Promise<T> {
  if (!response.ok) {
    const details = await response.text();
    throw new Error(
      `${endpoint} failed with HTTP ${response.status}${details ? `: ${details.slice(0, 180)}` : ""}`,
    );
  }

  const payload = (await response.json()) as T;
  if (typeof payload.code === "number" && payload.code !== 0) {
    throw new Error(`${endpoint} failed: ${payload.msg ?? payload.code}`);
  }

  return payload;
}
