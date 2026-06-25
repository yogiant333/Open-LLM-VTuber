import { Clock3, Keyboard, MessageSquareX, Mic, MicOff, PlugZap, Radio, RotateCcw, Send, Square, Wifi, WifiOff } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LiveTalkingClient } from "./livetalking";
import type { BackendMessage, ChatLine, ConnectionState } from "./types";

const LIVETALKING_URL = "http://127.0.0.1:18010";
const LIVETALKING_AVATAR_ID = "xiaomeng_wav2lip256";
const BACKEND_WS_URL = "ws://127.0.0.1:18080/client-ws";

const WAKE_TEXT = "请说 小孟小孟 唤醒";
const INITIAL_ANSWER_TEXT = "我是小梦数字人，可以通过实时语音和视频为你讲解内容。";

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

function getStatusClass(state: ConnectionState) {
  if (state === "ready" || state === "speaking") return "is-good";
  if (state === "connecting" || state === "thinking") return "is-warn";
  if (state === "error") return "is-bad";
  return "is-muted";
}

function getMicStatusLabel(state: ConnectionState) {
  const labels: Record<ConnectionState, string> = {
    disconnected: "未启用",
    connecting: "请求中",
    ready: "已启用",
    thinking: "请求中",
    speaking: "已启用",
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
  text: string;
}

function wait(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
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

function getRmsLevel(samples: Float32Array) {
  if (samples.length === 0) {
    return 0;
  }

  let sum = 0;
  let peak = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const sample = samples[index];
    const abs = Math.abs(sample);
    peak = Math.max(peak, abs);
    sum += sample * sample;
  }

  const rms = Math.sqrt(sum / samples.length);
  return Math.min(1, Math.max(rms * 60, peak * 3.2));
}

export function App() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const websocketRef = useRef<WebSocket | null>(null);
  const liveTalkingRef = useRef<LiveTalkingClient | null>(null);
  const micCaptureRef = useRef<MicCapture | null>(null);
  const volumeBarRef = useRef<HTMLElement | null>(null);
  const answerListRef = useRef<HTMLDivElement | null>(null);
  const volumeLevelRef = useRef(0);
  const activeAnswerIdRef = useRef("");
  const playbackQueueRef = useRef<PlaybackTask[]>([]);
  const isPlaybackQueueRunningRef = useRef(false);
  const backendSynthCompleteRef = useRef(false);
  const [time, setTime] = useState(nowTime);
  const [state, setState] = useState<ConnectionState>("disconnected");
  const [statusMessage, setStatusMessage] = useState("正在等待连接数字人服务");
  const [backendState, setBackendState] = useState<ConnectionState>("disconnected");
  const [micState, setMicState] = useState<ConnectionState>("disconnected");
  const [sessionId, setSessionId] = useState("");
  const [isAwake, setIsAwake] = useState(false);
  const [subtitle, setSubtitle] = useState(WAKE_TEXT);
  const [answerText, setAnswerText] = useState(INITIAL_ANSWER_TEXT);
  const [answerEntries, setAnswerEntries] = useState<AnswerEntry[]>([]);
  const [question, setQuestion] = useState("");
  const [isInputOpen, setIsInputOpen] = useState(false);
  const [chatLines, setChatLines] = useState<ChatLine[]>([
    makeLine("system", "展示页已加载，准备连接 LiveTalking 和 Open-LLM-VTuber。"),
  ]);

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
    try {
      while (playbackQueueRef.current.length > 0) {
        const task = playbackQueueRef.current.shift();
        const client = liveTalkingRef.current;
        if (!task || !client?.getSessionId()) {
          continue;
        }

        setIsAwake(true);
        setSubtitle(task.text);
        setState("speaking");
        setStatusMessage("正在将语音转发给 LiveTalking");
        websocketRef.current?.send(
          JSON.stringify({
            type: "audio-play-start",
            display_text: task.displayText,
          }),
        );

        try {
          await client.sendAudio(task.audio);
          const durationMs = getWavDurationMs(task.audio);
          await wait(durationMs + 900);
          setState("ready");
          setStatusMessage("数字人已待命");
        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : String(error);
          setState("error");
          setStatusMessage(errorMessage);
          appendLine("system", `音频转发失败：${errorMessage}`);
        }
      }
    } finally {
      isPlaybackQueueRunningRef.current = false;
      notifyPlaybackCompleteIfReady();
    }
  }, [appendLine, notifyPlaybackCompleteIfReady]);

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
    if (volumeBarRef.current) {
      volumeBarRef.current.style.transform = "scaleX(0.03)";
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
        const nextLevel = volumeLevelRef.current * 0.55 + getRmsLevel(visualSamples) * 0.45;
        volumeLevelRef.current = nextLevel;
        if (volumeBarRef.current) {
          volumeBarRef.current.style.transform = `scaleX(${Math.max(0.03, nextLevel)})`;
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
          text: text || WAKE_TEXT,
        });
        processPlaybackQueue().catch(() => undefined);
      }

      if (message.type === "backend-synth-complete") {
        backendSynthCompleteRef.current = true;
        notifyPlaybackCompleteIfReady();
      }

      if (message.type === "conversation-cleared") {
        const successText = message.success === false ? "后端会话清空失败" : "会话已清空";
        setStatusMessage(successText);
        appendLine("system", successText);
      }

      if (message.type === "control" && message.text) {
        setStatusMessage(message.text);
        if (message.text === "start-mic") {
          startMicrophone().catch(() => undefined);
        }
        if (message.text === "mic-audio-end") {
          setIsAwake(true);
          resetAnswerDraft();
        }
        if (message.text === "wakeup-detected") {
          setIsAwake(true);
          setSubtitle("我在，请说。");
        }
        if (message.text === "wakeup-timeout") {
          setIsAwake(false);
          setSubtitle(WAKE_TEXT);
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
  ]);

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
    websocketRef.current?.send(JSON.stringify({ type: "interrupt-signal" }));
    try {
      await liveTalkingRef.current?.interrupt();
      setState("ready");
      setStatusMessage("已打断当前讲解");
      setIsAwake(false);
      setSubtitle(WAKE_TEXT);
      activeAnswerIdRef.current = "";
      appendLine("system", "已执行打断。");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setState("error");
      setStatusMessage(message);
    }
  };

  const handleClearConversation = () => {
    websocketRef.current?.send(JSON.stringify({ type: "clear-conversation" }));
    playbackQueueRef.current = [];
    backendSynthCompleteRef.current = false;
    activeAnswerIdRef.current = "";
    setAnswerEntries([]);
    setAnswerText("");
    setQuestion("");
    setIsAwake(false);
    setSubtitle(WAKE_TEXT);
    setStatusMessage("正在清空会话");
  };

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

        <div className="overlay-status">
          <span className={`status-dot ${getStatusClass(state)}`}>
            <Radio size={12} />
            数字人 {getStatusLabel(state)}
          </span>
          <span className={`status-dot ${getStatusClass(backendState)}`}>
            {backendState === "ready" ? <Wifi size={12} /> : <WifiOff size={12} />}
            后端 {getStatusLabel(backendState)}
          </span>
          <span className={`status-dot ${getStatusClass(micState)}`}>
            {micState === "ready" ? <Mic size={12} /> : <MicOff size={12} />}
            麦克风 {getMicStatusLabel(micState)}
          </span>
        </div>

        <div className="volume-meter" aria-label="麦克风音量">
          <span>MIC</span>
          <div className="volume-track">
            <i ref={volumeBarRef} />
          </div>
        </div>

        <div className="wake-caption">
          <p>{isAwake ? subtitle : WAKE_TEXT}</p>
        </div>

        <div className="floating-actions">
          <button title="重新连接" onClick={connectLiveTalking}>
            <RotateCcw size={18} />
          </button>
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
          <button title="打断" onClick={handleInterrupt}>
            <Square size={16} />
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
