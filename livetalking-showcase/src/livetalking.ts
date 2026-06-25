import type { LiveTalkingConfig, OfferResponse } from "./types";

export class LiveTalkingClient {
  private peerConnection: RTCPeerConnection | null = null;
  private sessionId: string | null = null;
  private audioAbortController: AbortController | null = null;

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
    return answer.sessionid;
  }

  async sendAudio(audioBase64: string) {
    if (!this.sessionId) {
      throw new Error("LiveTalking session is not connected");
    }

    const formData = new FormData();
    formData.append("sessionid", this.sessionId);
    formData.append("file", base64WavToBlob(audioBase64), "reply.wav");

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
    if (!this.peerConnection) {
      return;
    }

    this.peerConnection.getSenders().forEach((sender) => sender.track?.stop());
    this.peerConnection
      .getReceivers()
      .forEach((receiver) => receiver.track?.stop());
    this.audioAbortController?.abort();
    this.audioAbortController = null;
    this.peerConnection.close();
    this.peerConnection = null;
    this.sessionId = null;
  }
}

function base64WavToBlob(base64: string) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Blob([bytes], { type: "audio/wav" });
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
