import {
  BarChart3,
  Clock3,
  Keyboard,
  MessageSquareX,
  Mic,
  MicOff,
  PlugZap,
  Send,
  SlidersHorizontal,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LiveTalkingClient } from "./livetalking";
import type { BackendMessage, ChatLine, ConnectionState } from "./types";

const LIVETALKING_URL = "/livetalking";
const LIVETALKING_AVATAR_ID = "xiaomeng_wav2lip256";
const BACKEND_WS_URL = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/client-ws`;

const WAKE_TEXT = "请说 小孟小孟 唤醒";
const INITIAL_ANSWER_TEXT = "我是小梦数字人，可以通过实时语音和视频为你讲解内容。";
const DEFAULT_RMS_THRESHOLD_DBFS = -48;
const DEFAULT_PEAK_THRESHOLD_DBFS = -36;
const AUDIO_HISTORY_LIMIT = 160;

function nowTime() {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date());
}

function nowDate() {
  const date = new Date();
  const dateText = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .format(date)
    .replace(/\//g, ".");
  const weekday = new Intl.DateTimeFormat("zh-CN", {
    weekday: "long",
  }).format(date);
  return `${dateText} ${weekday}`;
}

function getStatusLabel(state: ConnectionState) {
  const labels: Record<ConnectionState, string> = {
    disconnected: "未连接",
    connecting: "连接中",
    ready: "待命",
    thinking: "生成中",
    speaking: "讲解中",
    error: "异常",
  };
  return labels[state];
}

function makeLine(role: ChatLine["role"], text: string): ChatLine {
  return {
    id: crypto.randomUUID(),
    role,
    text,
    time: nowTime(),
  };
}

interface MicCapture {
  audioContext: AudioContext;
  source: MediaStreamAudioSourceNode;
  analyser: AnalyserNode;
  processor: ScriptProcessorNode;
  stream: MediaStream;
  pending: number[];
  animationFrameId: number;
}

interface AnswerEntry {
  id: string;
  text: string;
}

interface PlaybackTask {
  audio: string;
  displayText?: BackendMessage["display_text"];
  serverPerf?: BackendMessage["server_perf"];
  text: string;
  receivedAtMs: number;
}

interface WebRtcStatsSnapshot {
  resolution: string;
  fps: string;
  bitrateKbps: string;
  packetsLost: string;
  packetsReceived: string;
  jitterMs: string;
  roundTripMs: string;
  framesDecoded: string;
  freezeCount: string;
  qp: string;
}

interface WebRtcStatsSample {
  bytesReceived: number;
  timestamp: number;
}

const EMPTY_WEBRTC_STATS: WebRtcStatsSnapshot = {
  resolution: "-",
  fps: "-",
  bitrateKbps: "-",
  packetsLost: "-",
  packetsReceived: "-",
  jitterMs: "-",
  roundTripMs: "-",
  framesDecoded: "-",
  freezeCount: "-",
  qp: "-",
};

function wait(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function byteLengthFromBase64(base64: string) {
  const padding = base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0;
  return Math.max(0, Math.floor((base64.length * 3) / 4) - padding);
}

function readAscii(bytes: Uint8Array, offset: number, length: number) {
  return String.fromCharCode(...bytes.slice(offset, offset + length));
}

function readUint32LE(bytes: Uint8Array, offset: number) {
  return (
    bytes[offset] |
    (bytes[offset + 1] << 8) |
    (bytes[offset + 2] << 16) |
    (bytes[offset + 3] << 24)
  ) >>> 0;
}

function readUint16LE(bytes: Uint8Array, offset: number) {
  return bytes[offset] | (bytes[offset + 1] << 8);
}

function getWavDurationMs(base64: string) {
  try {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }

    let offset = 12;
    let sampleRate = 0;
    let channels = 0;
    let bitsPerSample = 0;
    let dataBytes = 0;
    while (offset + 8 <= bytes.length) {
      const chunkId = readAscii(bytes, offset, 4);
      const chunkSize = readUint32LE(bytes, offset + 4);
      const dataOffset = offset + 8;
      if (chunkId === "fmt ") {
        channels = readUint16LE(bytes, dataOffset + 2);
        sampleRate = readUint32LE(bytes, dataOffset + 4);
        bitsPerSample = readUint16LE(bytes, dataOffset + 14);
      }
      if (chunkId === "data") {
        dataBytes = chunkSize;
        break;
      }
      offset = dataOffset + chunkSize + (chunkSize % 2);
    }

    const bytesPerSecond = sampleRate * channels * (bitsPerSample / 8);
    if (!bytesPerSecond || !dataBytes) {
      return 2200;
    }
    return Math.max(800, Math.round((dataBytes / bytesPerSecond) * 1000));
  } catch {
    return 2200;
  }
}

function resampleFloat32(input: Float32Array, fromRate: number, toRate: number) {
  if (fromRate === toRate) {
    return Array.from(input);
  }

  const ratio = fromRate / toRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Array<number>(outputLength);

  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = index * ratio;
    const before = Math.floor(sourceIndex);
    const after = Math.min(before + 1, input.length - 1);
    const weight = sourceIndex - before;
    output[index] = input[before] * (1 - weight) + input[after] * weight;
  }

  return output;
}

type VolumeQuality = "silent" | "low" | "good" | "loud";

interface VolumeLevel {
  rmsDbfs: number;
  peakDbfs: number;
  meter: number;
  quality: VolumeQuality;
}

function getAudioLevel(samples: Float32Array): VolumeLevel {
  if (samples.length === 0) {
    return {
      rmsDbfs: -100,
      peakDbfs: -100,
      meter: 0,
      quality: "silent",
    };
  }

  let sum = 0;
  let peak = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.abs(samples[index]);
    sum += sample * sample;
    peak = Math.max(peak, sample);
  }

  const rms = Math.sqrt(sum / samples.length);
  const rmsDbfs = 20 * Math.log10(Math.max(rms, 0.00001));
  const peakDbfs = 20 * Math.log10(Math.max(peak, 0.00001));
  const normalized = Math.min(1, Math.max(0, (rmsDbfs + 54) / 38));
  const meter = normalized * 0.9;
  let quality: VolumeQuality = "silent";

  if (rmsDbfs > -16) {
    quality = "loud";
  } else if (rmsDbfs >= -34) {
    quality = "good";
  } else if (rmsDbfs >= -46) {
    quality = "low";
  }

  return {
    rmsDbfs,
    peakDbfs,
    meter,
    quality,
  };
}

function getVolumeQualityText(quality: VolumeQuality) {
  const labels: Record<VolumeQuality, string> = {
    silent: "未检测到人声",
    low: "声音偏小",
    good: "音量可识别",
    loud: "声音过响",
  };
  return labels[quality];
}

function formatVolumeDbfs(dbfs: number) {
  if (dbfs <= -99) {
    return "-∞ dB";
  }
  return `${Math.round(dbfs)} dB`;
}

interface AudioHistoryPoint {
  rmsDbfs: number;
  peakDbfs: number;
  time: number;
}

function dbfsToChartY(dbfs: number) {
  const clamped = Math.min(-10, Math.max(-80, dbfs));
  return 92 - ((clamped + 80) / 70) * 84;
}

function pointsToPath(points: AudioHistoryPoint[], key: "rmsDbfs" | "peakDbfs") {
  if (points.length === 0) {
    return "";
  }

  const lastIndex = Math.max(1, points.length - 1);
  return points
    .map((point, index) => {
      const x = (index / lastIndex) * 100;
      const y = dbfsToChartY(point[key]);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

export function App() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const websocketRef = useRef<WebSocket | null>(null);
  const liveTalkingRef = useRef<LiveTalkingClient | null>(null);
  const micCaptureRef = useRef<MicCapture | null>(null);
  const volumeBarRef = useRef<HTMLElement | null>(null);
  const answerListRef = useRef<HTMLDivElement | null>(null);
  const userTranscriptRef = useRef<HTMLDivElement | null>(null);
  const volumeLevelRef = useRef(0);
  const volumeQualityRef = useRef<VolumeQuality>("silent");
  const volumeDbfsRef = useRef(-100);
  const peakDbfsRef = useRef(-100);
  const audioHistoryLastUpdateRef = useRef(0);
  const rmsThresholdRef = useRef(DEFAULT_RMS_THRESHOLD_DBFS);
  const peakThresholdRef = useRef(DEFAULT_PEAK_THRESHOLD_DBFS);
  const activeAnswerIdRef = useRef("");
  const playbackQueueRef = useRef<PlaybackTask[]>([]);
  const isPlaybackQueueRunningRef = useRef(false);
  const backendSynthCompleteRef = useRef(false);
  const playbackGenerationRef = useRef(0);
  const previousStatsSampleRef = useRef<WebRtcStatsSample | null>(null);
  const [time, setTime] = useState(nowTime);
  const [state, setState] = useState<ConnectionState>("disconnected");
  const [statusMessage, setStatusMessage] = useState("正在等待连接数字人服务");
  const [backendState, setBackendState] = useState<ConnectionState>("disconnected");
  const [micState, setMicState] = useState<ConnectionState>("disconnected");
  const [sessionId, setSessionId] = useState("");
  const [isAwake, setIsAwake] = useState(false);
  const [subtitle, setSubtitle] = useState(WAKE_TEXT);
  const [userTranscript, setUserTranscript] = useState("");
  const [isUserTranscriptFinal, setIsUserTranscriptFinal] = useState(false);
  const [answerText, setAnswerText] = useState(INITIAL_ANSWER_TEXT);
  const [answerEntries, setAnswerEntries] = useState<AnswerEntry[]>([]);
  const [isStatsOpen, setIsStatsOpen] = useState(false);
  const [isAudioDebugOpen, setIsAudioDebugOpen] = useState(false);
  const [webRtcStats, setWebRtcStats] = useState<WebRtcStatsSnapshot>(EMPTY_WEBRTC_STATS);
  const [volumeQuality, setVolumeQuality] = useState<VolumeQuality>("silent");
  const [volumeDbfs, setVolumeDbfs] = useState(-100);
  const [peakDbfs, setPeakDbfs] = useState(-100);
  const [audioHistory, setAudioHistory] = useState<AudioHistoryPoint[]>([]);
  const [rmsThresholdDbfs, setRmsThresholdDbfs] = useState(() => {
    const saved = Number(localStorage.getItem("showcase-rms-threshold-dbfs"));
    return Number.isFinite(saved) ? saved : DEFAULT_RMS_THRESHOLD_DBFS;
  });
  const [peakThresholdDbfs, setPeakThresholdDbfs] = useState(() => {
    const saved = Number(localStorage.getItem("showcase-peak-threshold-dbfs"));
    return Number.isFinite(saved) ? saved : DEFAULT_PEAK_THRESHOLD_DBFS;
  });
  const [question, setQuestion] = useState("");
  const [isInputOpen, setIsInputOpen] = useState(false);
  const [chatLines, setChatLines] = useState<ChatLine[]>([
    makeLine("system", "展示页已加载，准备连接 LiveTalking 和 Open-LLM-VTuber。"),
  ]);

  rmsThresholdRef.current = rmsThresholdDbfs;
  peakThresholdRef.current = peakThresholdDbfs;

  const liveTalkingConfig = useMemo(
    () => ({
      serviceUrl: LIVETALKING_URL,
      avatarId: LIVETALKING_AVATAR_ID,
      useStun: false,
    }),
    [],
  );

  const appendLine = useCallback((role: ChatLine["role"], text: string) => {
    setChatLines((current) => [makeLine(role, text), ...current].slice(0, 7));
  }, []);

  const sendUtteranceFilterConfig = useCallback((rmsDbfs: number, peakDbfsValue: number) => {
    const websocket = websocketRef.current;
    if (websocket?.readyState !== WebSocket.OPEN) {
      return;
    }
    websocket.send(
      JSON.stringify({
        type: "utterance-filter-config-update",
        min_rms_dbfs: rmsDbfs,
        min_peak_dbfs: peakDbfsValue,
      }),
    );
  }, []);

  const refreshWebRtcStats = useCallback(async () => {
    const statsReport = await liveTalkingRef.current?.getStats();
    if (!statsReport) {
      setWebRtcStats(EMPTY_WEBRTC_STATS);
      previousStatsSampleRef.current = null;
      return;
    }

    let inboundVideo: RTCInboundRtpStreamStats | undefined;
    let selectedPair: RTCIceCandidatePairStats | undefined;
    statsReport.forEach((report) => {
      if (report.type === "inbound-rtp" && report.kind === "video") {
        inboundVideo = report as RTCInboundRtpStreamStats;
      }
      if (report.type === "candidate-pair" && report.state === "succeeded" && report.nominated) {
        selectedPair = report as RTCIceCandidatePairStats;
      }
    });

    if (!inboundVideo) {
      setWebRtcStats(EMPTY_WEBRTC_STATS);
      previousStatsSampleRef.current = null;
      return;
    }

    const bytesReceived = inboundVideo.bytesReceived ?? 0;
    const timestamp = inboundVideo.timestamp;
    const previous = previousStatsSampleRef.current;
    let bitrateKbps = "-";
    if (previous && timestamp > previous.timestamp) {
      const deltaBytes = bytesReceived - previous.bytesReceived;
      const deltaSeconds = (timestamp - previous.timestamp) / 1000;
      bitrateKbps = Math.max(0, Math.round((deltaBytes * 8) / deltaSeconds / 1000)).toString();
    }
    previousStatsSampleRef.current = { bytesReceived, timestamp };

    const frameWidth = inboundVideo.frameWidth;
    const frameHeight = inboundVideo.frameHeight;
    const framesDecoded = inboundVideo.framesDecoded ?? 0;
    const qpSum = inboundVideo.qpSum;
    const extendedInboundVideo = inboundVideo as RTCInboundRtpStreamStats & {
      freezeCount?: number;
    };
    const avgQp = qpSum && framesDecoded ? Math.round(qpSum / framesDecoded).toString() : "-";

    setWebRtcStats({
      resolution: frameWidth && frameHeight ? `${frameWidth}x${frameHeight}` : "-",
      fps: typeof inboundVideo.framesPerSecond === "number" ? inboundVideo.framesPerSecond.toFixed(1) : "-",
      bitrateKbps,
      packetsLost: String(inboundVideo.packetsLost ?? "-"),
      packetsReceived: String(inboundVideo.packetsReceived ?? "-"),
      jitterMs: typeof inboundVideo.jitter === "number" ? Math.round(inboundVideo.jitter * 1000).toString() : "-",
      roundTripMs:
        selectedPair && typeof selectedPair.currentRoundTripTime === "number"
          ? Math.round(selectedPair.currentRoundTripTime * 1000).toString()
          : "-",
      framesDecoded: String(framesDecoded || "-"),
      freezeCount: String(extendedInboundVideo.freezeCount ?? "-"),
      qp: avgQp,
    });
  }, []);

  const resetAnswerDraft = useCallback(() => {
    activeAnswerIdRef.current = "";
    setAnswerText("");
  }, []);

  const appendAnswerChunk = useCallback((text: string) => {
    const chunk = text.trim();
    if (!chunk) {
      return "";
    }

    let activeId = activeAnswerIdRef.current;
    if (!activeId) {
      activeId = crypto.randomUUID();
      activeAnswerIdRef.current = activeId;
    }

    let nextText = chunk;
    setAnswerEntries((current) => {
      const existing = current.find((entry) => entry.id === activeId);
      const currentText = existing?.text.trim() ?? "";
      if (currentText && currentText !== chunk) {
        if (chunk.startsWith(currentText)) {
          nextText = chunk;
        } else if (currentText.endsWith(chunk)) {
          nextText = currentText;
        } else {
          nextText = `${currentText}${chunk}`;
        }
      } else if (currentText) {
        nextText = currentText;
      }

      const withoutActive = current.filter((entry) => entry.id !== activeId);
      return [...withoutActive, { id: activeId, text: nextText }].slice(-5);
    });
    setAnswerText(nextText);
    return nextText;
  }, []);

  const notifyPlaybackCompleteIfReady = useCallback(() => {
    if (
      !backendSynthCompleteRef.current ||
      isPlaybackQueueRunningRef.current ||
      playbackQueueRef.current.length > 0
    ) {
      return;
    }

    backendSynthCompleteRef.current = false;
    websocketRef.current?.send(JSON.stringify({ type: "frontend-playback-complete" }));
  }, []);

  const processPlaybackQueue = useCallback(async () => {
    if (isPlaybackQueueRunningRef.current) {
      return;
    }

    isPlaybackQueueRunningRef.current = true;
    const playbackGeneration = playbackGenerationRef.current;
    try {
      while (
        playbackGenerationRef.current === playbackGeneration &&
        playbackQueueRef.current.length > 0
      ) {
        const task = playbackQueueRef.current.shift();
        const client = liveTalkingRef.current;
        if (!task || !client?.getSessionId()) {
          continue;
        }

        setIsAwake(true);
        setSubtitle(task.text);
        setState("speaking");
        setStatusMessage("正在将语音转发给 LiveTalking");
        const audioDurationMs = getWavDurationMs(task.audio);
        const sendStartedAtMs = performance.now();
        websocketRef.current?.send(
          JSON.stringify({
            type: "audio-play-start",
            display_text: task.displayText,
            phase: "livetalking_send_start",
            server_perf: task.serverPerf,
            audio_duration_ms: Math.round(audioDurationMs),
            audio_bytes: byteLengthFromBase64(task.audio),
            client_queue_wait_ms: Math.round(sendStartedAtMs - task.receivedAtMs),
          }),
        );

        try {
          await client.sendAudio(task.audio);
          const sentAtMs = performance.now();
          websocketRef.current?.send(
            JSON.stringify({
              type: "audio-play-event",
              phase: "livetalking_send_done",
              server_perf: task.serverPerf,
              audio_duration_ms: Math.round(audioDurationMs),
              client_send_ms: Math.round(sentAtMs - sendStartedAtMs),
              client_since_received_ms: Math.round(sentAtMs - task.receivedAtMs),
            }),
          );
          await wait(audioDurationMs + 900);
          const waitedAtMs = performance.now();
          websocketRef.current?.send(
            JSON.stringify({
              type: "audio-play-event",
              phase: "segment_wait_done",
              server_perf: task.serverPerf,
              audio_duration_ms: Math.round(audioDurationMs),
              client_since_received_ms: Math.round(waitedAtMs - task.receivedAtMs),
            }),
          );
          if (task.serverPerf?.source === "wakeup_ack_cache") {
            websocketRef.current?.send(JSON.stringify({ type: "frontend-playback-complete" }));
          }
          if (playbackGenerationRef.current !== playbackGeneration) {
            break;
          }
          setState("ready");
          setStatusMessage("数字人已待命");
        } catch (error) {
          if (playbackGenerationRef.current !== playbackGeneration) {
            break;
          }
          const errorMessage = error instanceof Error ? error.message : String(error);
          setState("error");
          setStatusMessage(errorMessage);
          appendLine("system", `音频转发失败：${errorMessage}`);
        }
      }
    } finally {
      if (playbackGenerationRef.current === playbackGeneration) {
        isPlaybackQueueRunningRef.current = false;
        notifyPlaybackCompleteIfReady();
      }
    }
  }, [appendLine, notifyPlaybackCompleteIfReady]);

  const stopCurrentPlayback = useCallback(
    async (sendBackendInterrupt: boolean) => {
      if (sendBackendInterrupt) {
        websocketRef.current?.send(JSON.stringify({ type: "interrupt-signal" }));
      }

      playbackGenerationRef.current += 1;
      playbackQueueRef.current = [];
      backendSynthCompleteRef.current = false;
      websocketRef.current?.send(JSON.stringify({ type: "frontend-playback-complete" }));

      try {
        await liveTalkingRef.current?.interrupt();
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        appendLine("system", `LiveTalking 打断失败：${message}`);
      }

      isPlaybackQueueRunningRef.current = false;
      setState("ready");
      setStatusMessage("已打断当前讲解");
    },
    [appendLine],
  );

  const stopMicrophone = useCallback(() => {
    const capture = micCaptureRef.current;
    if (!capture) {
      return;
    }

    capture.processor.disconnect();
    capture.analyser.disconnect();
    capture.source.disconnect();
    window.cancelAnimationFrame(capture.animationFrameId);
    capture.stream.getTracks().forEach((track) => track.stop());
    capture.audioContext.close().catch(() => undefined);
    micCaptureRef.current = null;
    volumeLevelRef.current = 0;
    volumeQualityRef.current = "silent";
    volumeDbfsRef.current = -100;
    peakDbfsRef.current = -100;
    audioHistoryLastUpdateRef.current = 0;
    setVolumeQuality("silent");
    setVolumeDbfs(-100);
    setPeakDbfs(-100);
    setAudioHistory([]);
    if (volumeBarRef.current) {
      volumeBarRef.current.style.transform = "scaleX(0.03)";
      volumeBarRef.current.dataset.quality = "silent";
    }
    setMicState("disconnected");
  }, []);

  const resumeMicrophoneContext = useCallback(async () => {
    const capture = micCaptureRef.current;
    if (!capture || capture.audioContext.state !== "suspended") {
      return;
    }

    try {
      await capture.audioContext.resume();
      setMicState("ready");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setMicState("error");
      setStatusMessage(`麦克风音频上下文恢复失败：${message}`);
    }
  }, []);

  const startMicrophone = useCallback(async () => {
    if (micCaptureRef.current) {
      return;
    }

    const websocket = websocketRef.current;
    if (websocket?.readyState !== WebSocket.OPEN) {
      setMicState("error");
      setStatusMessage("后端未连接，无法启用麦克风");
      return;
    }

    setMicState("connecting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const AudioContextCtor =
        window.AudioContext ||
        (window as Window & { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext;
      if (!AudioContextCtor) {
        throw new Error("当前浏览器不支持 AudioContext");
      }
      const audioContext = new AudioContextCtor();
      await audioContext.resume();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.28;
      const processor = audioContext.createScriptProcessor(2048, 1, 1);
      const targetSampleRate = 16000;
      const frameMs = 40;
      const frameSamples = Math.round((targetSampleRate * frameMs) / 1000);
      const pending: number[] = [];
      const visualSamples = new Float32Array(analyser.fftSize);
      const updateVolumeMeter = () => {
        analyser.getFloatTimeDomainData(visualSamples);
        const audioLevel = getAudioLevel(visualSamples);
        const nextLevel = volumeLevelRef.current * 0.82 + audioLevel.meter * 0.18;
        volumeLevelRef.current = nextLevel;
        if (audioLevel.quality !== volumeQualityRef.current) {
          volumeQualityRef.current = audioLevel.quality;
          setVolumeQuality(audioLevel.quality);
        }
        const roundedDbfs = Math.round(audioLevel.rmsDbfs);
        if (roundedDbfs !== volumeDbfsRef.current) {
          volumeDbfsRef.current = roundedDbfs;
          setVolumeDbfs(roundedDbfs);
        }
        const roundedPeakDbfs = Math.round(audioLevel.peakDbfs);
        if (roundedPeakDbfs !== peakDbfsRef.current) {
          peakDbfsRef.current = roundedPeakDbfs;
          setPeakDbfs(roundedPeakDbfs);
        }
        const now = performance.now();
        if (now - audioHistoryLastUpdateRef.current > 90) {
          audioHistoryLastUpdateRef.current = now;
          setAudioHistory((current) =>
            [
              ...current,
              {
                rmsDbfs: audioLevel.rmsDbfs,
                peakDbfs: audioLevel.peakDbfs,
                time: Date.now(),
              },
            ].slice(-AUDIO_HISTORY_LIMIT),
          );
        }
        if (volumeBarRef.current) {
          volumeBarRef.current.style.transform = `scaleX(${Math.max(0.03, nextLevel)})`;
          volumeBarRef.current.dataset.quality = audioLevel.quality;
        }

        const capture = micCaptureRef.current;
        if (capture) {
          capture.animationFrameId = window.requestAnimationFrame(updateVolumeMeter);
        }
      };

      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);

        const activeWebsocket = websocketRef.current;
        if (activeWebsocket?.readyState !== WebSocket.OPEN) {
          return;
        }

        const resampled = resampleFloat32(
          input,
          audioContext.sampleRate,
          targetSampleRate,
        );
        pending.push(...resampled);

        while (pending.length >= frameSamples) {
          const frame = pending.splice(0, frameSamples);
          activeWebsocket.send(
            JSON.stringify({
              type: "raw-audio-data",
              audio_format: "pcm_f32le",
              sample_rate: targetSampleRate,
              channels: 1,
              frame_ms: frameMs,
              audio: frame,
            }),
          );
        }
      };

      source.connect(analyser);
      source.connect(processor);
      processor.connect(audioContext.destination);
      micCaptureRef.current = {
        audioContext,
        source,
        analyser,
        processor,
        stream,
        pending,
        animationFrameId: window.requestAnimationFrame(updateVolumeMeter),
      };
      setMicState("ready");
      setStatusMessage("麦克风已启用，请说 小孟小孟 唤醒");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setMicState("error");
      setStatusMessage(`麦克风启用失败：${message}`);
      appendLine("system", `麦克风启用失败：${message}`);
    }
  }, [appendLine]);

  useEffect(() => {
    const resume = () => {
      resumeMicrophoneContext().catch(() => undefined);
    };

    window.addEventListener("pointerdown", resume);
    window.addEventListener("keydown", resume);

    return () => {
      window.removeEventListener("pointerdown", resume);
      window.removeEventListener("keydown", resume);
    };
  }, [resumeMicrophoneContext]);

  const connectLiveTalking = useCallback(async () => {
    liveTalkingRef.current?.disconnect();
    const client = new LiveTalkingClient(liveTalkingConfig);
    liveTalkingRef.current = client;
    setState("connecting");
    setStatusMessage("正在协商 LiveTalking WebRTC 视频流");
    setSessionId("");

    try {
      const nextSessionId = await client.connect((stream) => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      });
      setSessionId(nextSessionId);
      setState("ready");
      setStatusMessage("数字人已连接，可以开始讲解");
      setIsAwake(false);
      setSubtitle(WAKE_TEXT);
      appendLine("system", `LiveTalking 已连接：${nextSessionId.slice(0, 8)}...`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setState("error");
      setStatusMessage(message);
      appendLine("system", `LiveTalking 连接失败：${message}`);
    }
  }, [appendLine, liveTalkingConfig]);

  const connectBackend = useCallback(() => {
    websocketRef.current?.close();
    setBackendState("connecting");
    const websocket = new WebSocket(BACKEND_WS_URL);
    websocketRef.current = websocket;

    websocket.onopen = () => {
      setBackendState("ready");
      appendLine("system", "Open-LLM-VTuber 后端已连接。");
      websocket.send(JSON.stringify({ type: "fetch-configs" }));
      websocket.send(JSON.stringify({ type: "utterance-filter-config-request" }));
      websocket.send(
        JSON.stringify({
          type: "utterance-filter-config-update",
          min_rms_dbfs: rmsThresholdRef.current,
          min_peak_dbfs: peakThresholdRef.current,
        }),
      );
      websocket.send(JSON.stringify({ type: "create-new-history" }));
      window.setTimeout(() => {
        startMicrophone().catch(() => undefined);
      }, 200);
    };

    websocket.onmessage = async (event) => {
      let message: BackendMessage;
      try {
        message = JSON.parse(event.data) as BackendMessage;
      } catch {
        return;
      }

      if (message.type === "audio" && message.audio) {
        const text = message.display_text?.text?.trim();
        if (text) {
          setIsAwake(true);
          appendAnswerChunk(text);
          appendLine("assistant", text);
        }

        const client = liveTalkingRef.current;
        if (!client?.getSessionId()) {
          setState("error");
          setStatusMessage("收到音频，但 LiveTalking 尚未连接");
          return;
        }

        playbackQueueRef.current.push({
          audio: message.audio,
          displayText: message.display_text,
          serverPerf: message.server_perf,
          text: text || WAKE_TEXT,
          receivedAtMs: performance.now(),
        });
        processPlaybackQueue().catch(() => undefined);
      }

      if (message.type === "backend-synth-complete") {
        backendSynthCompleteRef.current = true;
        activeAnswerIdRef.current = "";
        notifyPlaybackCompleteIfReady();
      }

      if (message.type === "user-input-transcription-stream") {
        const text = message.text?.trim() ?? "";
        if (text) {
          setIsAwake(true);
          setUserTranscript(text);
          setIsUserTranscriptFinal(Boolean(message.is_final));
        }
      }

      if (message.type === "user-input-transcription") {
        const text = message.text?.trim() ?? "";
        if (text) {
          setIsAwake(true);
          setUserTranscript(text);
          setIsUserTranscriptFinal(!message.rejected);
          appendLine("user", text);
        }
      }

      if (message.type === "conversation-cleared") {
        const successText = message.success === false ? "后端会话清空失败" : "会话已清空";
        setStatusMessage(successText);
        appendLine("system", successText);
      }

      if (message.type === "utterance-filter-config-state" && message.utterance_filter) {
        const nextRms = Number(message.utterance_filter.min_rms_dbfs);
        const nextPeak = Number(message.utterance_filter.min_peak_dbfs);
        if (Number.isFinite(nextRms)) {
          setRmsThresholdDbfs(nextRms);
        }
        if (Number.isFinite(nextPeak)) {
          setPeakThresholdDbfs(nextPeak);
        }
      }

      if (message.type === "control" && message.text) {
        setStatusMessage(message.text);
        if (message.text === "start-mic") {
          startMicrophone().catch(() => undefined);
        }
        if (message.text === "mic-audio-end") {
          setIsAwake(true);
        }
        if (message.text === "interrupt") {
          stopCurrentPlayback(false).catch(() => undefined);
        }
        if (message.text === "wakeup-detected") {
          setIsAwake(true);
          setSubtitle("我在，请说。");
          setUserTranscript("");
          setIsUserTranscriptFinal(false);
        }
        if (message.text === "wakeup-timeout") {
          setIsAwake(false);
          setSubtitle(WAKE_TEXT);
          setUserTranscript("");
          setIsUserTranscriptFinal(false);
        }
      }
    };

    websocket.onclose = () => {
      setBackendState("disconnected");
      appendLine("system", "Open-LLM-VTuber 后端连接已断开。");
    };

    websocket.onerror = () => {
      setBackendState("error");
      appendLine("system", "Open-LLM-VTuber 后端连接异常。");
    };
  }, [
    appendAnswerChunk,
    appendLine,
    notifyPlaybackCompleteIfReady,
    processPlaybackQueue,
    resetAnswerDraft,
    startMicrophone,
    stopCurrentPlayback,
  ]);

  useEffect(() => {
    rmsThresholdRef.current = rmsThresholdDbfs;
    peakThresholdRef.current = peakThresholdDbfs;
    localStorage.setItem("showcase-rms-threshold-dbfs", String(rmsThresholdDbfs));
    localStorage.setItem("showcase-peak-threshold-dbfs", String(peakThresholdDbfs));
    const timeoutId = window.setTimeout(() => {
      sendUtteranceFilterConfig(rmsThresholdDbfs, peakThresholdDbfs);
    }, 180);
    return () => window.clearTimeout(timeoutId);
  }, [peakThresholdDbfs, rmsThresholdDbfs, sendUtteranceFilterConfig]);

  useEffect(() => {
    const tick = window.setInterval(() => setTime(nowTime()), 1000);
    connectLiveTalking();
    connectBackend();

    return () => {
      window.clearInterval(tick);
      websocketRef.current?.close();
      liveTalkingRef.current?.disconnect();
      stopMicrophone();
    };
  }, [connectBackend, connectLiveTalking, stopMicrophone]);

  useEffect(() => {
    const answerList = answerListRef.current;
    if (!answerList) {
      return;
    }

    window.setTimeout(() => {
      answerList.scrollTo({
        top: answerList.scrollHeight,
        behavior: "smooth",
      });
    }, 80);
  }, [answerEntries]);

  useEffect(() => {
    const transcriptPanel = userTranscriptRef.current;
    if (!transcriptPanel) {
      return;
    }

    window.setTimeout(() => {
      transcriptPanel.scrollTo({
        top: transcriptPanel.scrollHeight,
        behavior: "smooth",
      });
    }, 80);
  }, [userTranscript]);

  useEffect(() => {
    if (!isStatsOpen) {
      return;
    }

    refreshWebRtcStats().catch(() => undefined);
    const intervalId = window.setInterval(() => {
      refreshWebRtcStats().catch(() => undefined);
    }, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [isStatsOpen, refreshWebRtcStats]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;

    if (websocketRef.current?.readyState !== WebSocket.OPEN) {
      appendLine("system", "后端未连接，无法发送问题。");
      setBackendState("error");
      return;
    }

    websocketRef.current.send(JSON.stringify({ type: "text-input", text }));
    appendLine("user", text);
    resetAnswerDraft();
    setIsAwake(true);
    setSubtitle("正在组织回答，请稍候。");
    setState("thinking");
    setStatusMessage("Open-LLM-VTuber 正在生成回复");
    setQuestion("");
  };

  const handleInterrupt = async () => {
    await stopCurrentPlayback(true);
    setIsAwake(false);
    setSubtitle(WAKE_TEXT);
    activeAnswerIdRef.current = "";
    appendLine("system", "已执行打断。");
  };

  const handleClearConversation = () => {
    websocketRef.current?.send(JSON.stringify({ type: "clear-conversation" }));
    playbackQueueRef.current = [];
    backendSynthCompleteRef.current = false;
    activeAnswerIdRef.current = "";
    setAnswerEntries([]);
    setAnswerText("");
    setQuestion("");
    setUserTranscript("");
    setIsUserTranscriptFinal(false);
    setIsAwake(false);
    setSubtitle(WAKE_TEXT);
    setStatusMessage("正在清空会话");
  };

  const rmsPath = useMemo(() => pointsToPath(audioHistory, "rmsDbfs"), [audioHistory]);
  const peakPath = useMemo(() => pointsToPath(audioHistory, "peakDbfs"), [audioHistory]);
  const rmsThresholdY = dbfsToChartY(rmsThresholdDbfs);
  const peakThresholdY = dbfsToChartY(peakThresholdDbfs);
  const isCurrentVoiceAccepted =
    volumeDbfs >= rmsThresholdDbfs && peakDbfs >= peakThresholdDbfs;

  return (
    <main className="showcase-shell">
      <span className="sr-only">LiveTalking xiaomeng portrait showcase</span>
      <section className="portrait-stage" aria-label="LiveTalking 数字人竖屏舞台">
        <video ref={videoRef} className="avatar-video" autoPlay playsInline />
        <div className="stage-vignette" />
        <div className="stage-glow" />

        <header className="overlay-top">
          <div className="scene-clock">
            <Clock3 size={14} />
            <span>{nowDate()}</span>
            <strong>{time}</strong>
          </div>
          <div className="webrtc-stats-wrap">
            <button
              className={`stats-toggle ${isAudioDebugOpen ? "is-active" : ""}`}
              title="音频阈值调试"
              onClick={() => setIsAudioDebugOpen((current) => !current)}
            >
              <SlidersHorizontal size={15} />
            </button>
            <button
              className={`stats-toggle ${isStatsOpen ? "is-active" : ""}`}
              title="WebRTC 实时统计"
              onClick={() => setIsStatsOpen((current) => !current)}
            >
              <BarChart3 size={15} />
            </button>
            {isStatsOpen && (
              <div className="webrtc-stats-panel">
                <strong>WebRTC</strong>
                <dl>
                  <div>
                    <dt>RES</dt>
                    <dd>{webRtcStats.resolution}</dd>
                  </div>
                  <div>
                    <dt>FPS</dt>
                    <dd>{webRtcStats.fps}</dd>
                  </div>
                  <div>
                    <dt>KBPS</dt>
                    <dd>{webRtcStats.bitrateKbps}</dd>
                  </div>
                  <div>
                    <dt>RTT</dt>
                    <dd>{webRtcStats.roundTripMs}ms</dd>
                  </div>
                  <div>
                    <dt>JIT</dt>
                    <dd>{webRtcStats.jitterMs}ms</dd>
                  </div>
                  <div>
                    <dt>LOSS</dt>
                    <dd>{webRtcStats.packetsLost}</dd>
                  </div>
                  <div>
                    <dt>PKT</dt>
                    <dd>{webRtcStats.packetsReceived}</dd>
                  </div>
                  <div>
                    <dt>FRM</dt>
                    <dd>{webRtcStats.framesDecoded}</dd>
                  </div>
                  <div>
                    <dt>QP</dt>
                    <dd>{webRtcStats.qp}</dd>
                  </div>
                  <div>
                    <dt>FRZ</dt>
                    <dd>{webRtcStats.freezeCount}</dd>
                  </div>
                </dl>
              </div>
            )}
            {isAudioDebugOpen && (
              <div className="audio-debug-panel">
                <div className="audio-debug-title">
                  <strong>音频阈值</strong>
                  <span className={isCurrentVoiceAccepted ? "is-active" : ""}>
                    {isCurrentVoiceAccepted ? "可识别" : "未过线"}
                  </span>
                </div>
                <div className="audio-level-grid">
                  <div>
                    <span>RMS</span>
                    <strong>{formatVolumeDbfs(volumeDbfs)}</strong>
                  </div>
                  <div>
                    <span>PEAK</span>
                    <strong>{formatVolumeDbfs(peakDbfs)}</strong>
                  </div>
                </div>
                <svg className="audio-wave-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
                  <line x1="0" y1={rmsThresholdY} x2="100" y2={rmsThresholdY} className="rms-threshold" />
                  <line x1="0" y1={peakThresholdY} x2="100" y2={peakThresholdY} className="peak-threshold" />
                  <path d={peakPath} className="peak-line" />
                  <path d={rmsPath} className="rms-line" />
                </svg>
                <label className="threshold-control">
                  <span>
                    RMS 阈值
                    <em>{formatVolumeDbfs(rmsThresholdDbfs)}</em>
                  </span>
                  <input
                    type="range"
                    min="-70"
                    max="-20"
                    step="1"
                    value={rmsThresholdDbfs}
                    onChange={(event) => setRmsThresholdDbfs(Number(event.target.value))}
                  />
                </label>
                <label className="threshold-control">
                  <span>
                    Peak 阈值
                    <em>{formatVolumeDbfs(peakThresholdDbfs)}</em>
                  </span>
                  <input
                    type="range"
                    min="-60"
                    max="-10"
                    step="1"
                    value={peakThresholdDbfs}
                    onChange={(event) => setPeakThresholdDbfs(Number(event.target.value))}
                  />
                </label>
              </div>
            )}
          </div>
        </header>

        {state !== "ready" && state !== "speaking" && (
          <div className="stage-overlay">
            <div className="loader-ring" />
            <strong>{getStatusLabel(state)}</strong>
            <p>{statusMessage}</p>
            {(state === "error" || state === "disconnected") && (
              <button className="ghost-button" onClick={connectLiveTalking}>
                <PlugZap size={16} />
                重新连接
              </button>
            )}
          </div>
        )}

        {answerEntries.length > 0 && (
          <div className="answer-float">
            <span>当前讲解</span>
            <div className="answer-list" ref={answerListRef}>
              {answerEntries.map((entry) => (
                <p key={entry.id}>{entry.text}</p>
              ))}
            </div>
          </div>
        )}

        {userTranscript && (
          <div
            className={`user-transcript ${isUserTranscriptFinal ? "is-final" : ""}`}
            ref={userTranscriptRef}
          >
            <span>{isUserTranscriptFinal ? "已识别" : "正在识别"}</span>
            <p>{userTranscript}</p>
          </div>
        )}

        <div className="volume-meter" aria-label="麦克风音量">
          <span>MIC</span>
          <div className="volume-track">
            <i ref={volumeBarRef} data-quality={volumeQuality} />
          </div>
          <em title={getVolumeQualityText(volumeQuality)}>{formatVolumeDbfs(volumeDbfs)}</em>
        </div>

        <div className="wake-caption">
          <p>{isAwake ? subtitle : WAKE_TEXT}</p>
        </div>

        <div className="floating-actions">
          <button title="键盘输入" onClick={() => setIsInputOpen((current) => !current)}>
            <Keyboard size={18} />
          </button>
          <button title="清空会话" onClick={handleClearConversation}>
            <MessageSquareX size={18} />
          </button>
          <button
            title={micState === "ready" ? "关闭麦克风" : "启用麦克风"}
            onClick={() => {
              if (micCaptureRef.current?.audioContext.state === "suspended") {
                resumeMicrophoneContext().catch(() => undefined);
              } else if (micCaptureRef.current) {
                stopMicrophone();
              } else {
                startMicrophone().catch(() => undefined);
              }
            }}
          >
            {micState === "ready" ? <Mic size={18} /> : <MicOff size={18} />}
          </button>
        </div>

        {isInputOpen && (
          <form className="keyboard-panel" onSubmit={handleSubmit}>
            <label>
              <Mic size={18} />
              <input
                autoFocus
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="输入问题，或直接说“小孟小孟”唤醒"
              />
            </label>
            <button type="submit">
              <Send size={17} />
              发送
            </button>
          </form>
        )}

        <span className="session-watermark">
          {sessionId ? sessionId.slice(0, 8) : LIVETALKING_URL}
        </span>
      </section>
    </main>
  );
}
