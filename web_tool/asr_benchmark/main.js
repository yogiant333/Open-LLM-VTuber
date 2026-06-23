const API_BASE = window.location.origin;

const state = {
  providers: [],
  wavBlob: null,
  audioUrl: "",
  mediaRecorder: null,
  mediaStream: null,
  chunks: [],
  recordingStartedAt: 0,
  timerId: 0,
  waveformData: null,
};

const els = {
  statusLine: document.getElementById("statusLine"),
  backendMeta: document.getElementById("backendMeta"),
  audioMeta: document.getElementById("audioMeta"),
  providerList: document.getElementById("providerList"),
  hotwordsInput: document.getElementById("hotwordsInput"),
  referenceInput: document.getElementById("referenceInput"),
  recordButton: document.getElementById("recordButton"),
  stopButton: document.getElementById("stopButton"),
  playButton: document.getElementById("playButton"),
  runButton: document.getElementById("runButton"),
  refreshProviders: document.getElementById("refreshProviders"),
  audioFileInput: document.getElementById("audioFileInput"),
  audioPlayer: document.getElementById("audioPlayer"),
  waveform: document.getElementById("waveform"),
  recordingTime: document.getElementById("recordingTime"),
  resultsBody: document.getElementById("resultsBody"),
  clearResults: document.getElementById("clearResults"),
};

const canvasContext = els.waveform.getContext("2d");

function setStatus(text) {
  els.statusLine.textContent = text;
}

function formatMs(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${Math.round(value)} ms`;
}

function formatScore(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(3);
}

function formatClock(ms) {
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  const millis = Math.floor(ms % 1000);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

function getHotwords() {
  return els.hotwordsInput.value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function getSelectedProviders() {
  return [...els.providerList.querySelectorAll("input[type='checkbox']:checked")].map(
    (input) => input.value,
  );
}

async function loadProviders() {
  setStatus("正在读取 ASR 列表...");
  const response = await fetch(`${API_BASE}/api/asr-benchmark/providers`);
  if (!response.ok) throw new Error(`读取 ASR 列表失败：${response.status}`);
  const data = await response.json();
  state.providers = data.providers || [];
  els.hotwordsInput.value = (data.hotwords || []).join("\n");
  els.backendMeta.textContent = `当前 ASR：${data.current_asr || "-"}`;
  renderProviders();
  setStatus("后端已连接");
}

function renderProviders() {
  els.providerList.innerHTML = "";
  for (const provider of state.providers) {
    const row = document.createElement("label");
    row.className = `provider-item ${provider.available ? "" : "unavailable"}`;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = provider.name;
    checkbox.disabled = !provider.available;
    checkbox.checked = Boolean(provider.available && provider.enabled);

    const text = document.createElement("div");
    const name = document.createElement("div");
    name.className = "provider-name";
    name.textContent = provider.name;
    const reason = document.createElement("div");
    reason.className = "provider-reason";
    reason.textContent = provider.available
      ? `热词：${provider.mode || "none"}`
      : provider.reason || "unavailable";
    text.append(name, reason);

    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = provider.enabled ? "当前" : provider.available ? "可测" : "不可用";

    row.append(checkbox, text, chip);
    els.providerList.append(row);
  }
}

async function startRecording() {
  state.mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    },
  });

  state.chunks = [];
  state.mediaRecorder = new MediaRecorder(state.mediaStream);
  state.mediaRecorder.ondataavailable = (event) => {
    if (event.data.size > 0) state.chunks.push(event.data);
  };
  state.mediaRecorder.onstop = handleRecordingStopped;
  state.mediaRecorder.start();

  state.recordingStartedAt = performance.now();
  state.timerId = window.setInterval(updateRecordingTime, 33);
  els.recordButton.disabled = true;
  els.stopButton.disabled = false;
  els.runButton.disabled = true;
  setStatus("正在录音");
  drawEmptyWaveform(true);
}

function stopRecording() {
  if (state.mediaRecorder && state.mediaRecorder.state !== "inactive") {
    state.mediaRecorder.stop();
  }
  if (state.mediaStream) {
    state.mediaStream.getTracks().forEach((track) => track.stop());
  }
  window.clearInterval(state.timerId);
  els.stopButton.disabled = true;
  setStatus("正在处理录音...");
}

async function handleRecordingStopped() {
  try {
    const blob = new Blob(state.chunks, { type: state.mediaRecorder.mimeType });
    await setAudioBlob(blob, "recording.webm");
    setStatus("录音已就绪");
  } catch (error) {
    setStatus(error.message);
  } finally {
    els.recordButton.disabled = false;
  }
}

async function setAudioBlob(blob, fileName) {
  const arrayBuffer = await blob.arrayBuffer();
  const audioContext = new AudioContext();
  const decoded = await audioContext.decodeAudioData(arrayBuffer.slice(0));
  const wavBuffer = await audioBufferToWav16k(decoded);
  await audioContext.close();

  state.wavBlob = new Blob([wavBuffer], { type: "audio/wav" });
  if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
  state.audioUrl = URL.createObjectURL(state.wavBlob);
  els.audioPlayer.src = state.audioUrl;
  els.playButton.disabled = false;
  els.runButton.disabled = false;
  els.audioMeta.textContent = `${fileName} · ${formatMs(decoded.duration * 1000)} · 16 kHz mono`;
  drawWaveform(state.waveformData);
}

async function audioBufferToWav16k(audioBuffer) {
  const targetSampleRate = 16000;
  const mono = mixToMono(audioBuffer);
  const resampled = await resampleFloat32(mono, audioBuffer.sampleRate, targetSampleRate);
  state.waveformData = resampled;
  return encodeWav(resampled, targetSampleRate);
}

function mixToMono(audioBuffer) {
  const channelCount = audioBuffer.numberOfChannels;
  const length = audioBuffer.length;
  const mono = new Float32Array(length);
  for (let channel = 0; channel < channelCount; channel += 1) {
    const data = audioBuffer.getChannelData(channel);
    for (let i = 0; i < length; i += 1) {
      mono[i] += data[i] / channelCount;
    }
  }
  return mono;
}

async function resampleFloat32(samples, fromRate, toRate) {
  if (fromRate === toRate) return samples;
  const duration = samples.length / fromRate;
  const frameCount = Math.max(1, Math.round(duration * toRate));
  const offline = new OfflineAudioContext(1, frameCount, toRate);
  const buffer = offline.createBuffer(1, samples.length, fromRate);
  buffer.copyToChannel(samples, 0);
  const source = offline.createBufferSource();
  source.buffer = buffer;
  source.connect(offline.destination);
  source.start();
  const rendered = await offline.startRendering();
  return rendered.getChannelData(0).slice();
}

function encodeWav(samples, sampleRate) {
  const bytesPerSample = 2;
  const blockAlign = bytesPerSample;
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
  const view = new DataView(buffer);
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * bytesPerSample, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, samples.length * bytesPerSample, true);

  let offset = 44;
  for (const sample of samples) {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
    offset += 2;
  }
  return buffer;
}

function writeString(view, offset, value) {
  for (let i = 0; i < value.length; i += 1) {
    view.setUint8(offset + i, value.charCodeAt(i));
  }
}

function updateRecordingTime() {
  const elapsed = performance.now() - state.recordingStartedAt;
  els.recordingTime.textContent = formatClock(elapsed);
}

function drawEmptyWaveform(active = false) {
  const { width, height } = els.waveform;
  canvasContext.fillStyle = "#101820";
  canvasContext.fillRect(0, 0, width, height);
  canvasContext.strokeStyle = active ? "#6ee7b7" : "#466174";
  canvasContext.lineWidth = 2;
  canvasContext.beginPath();
  canvasContext.moveTo(0, height / 2);
  canvasContext.lineTo(width, height / 2);
  canvasContext.stroke();
}

function drawWaveform(samples) {
  if (!samples) {
    drawEmptyWaveform(false);
    return;
  }
  const { width, height } = els.waveform;
  canvasContext.fillStyle = "#101820";
  canvasContext.fillRect(0, 0, width, height);
  canvasContext.strokeStyle = "#5cc8ff";
  canvasContext.lineWidth = 1.5;
  canvasContext.beginPath();
  const step = Math.max(1, Math.floor(samples.length / width));
  for (let x = 0; x < width; x += 1) {
    let min = 1;
    let max = -1;
    for (let j = 0; j < step; j += 1) {
      const value = samples[x * step + j] || 0;
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
    const y1 = ((1 - max) * height) / 2;
    const y2 = ((1 - min) * height) / 2;
    canvasContext.moveTo(x, y1);
    canvasContext.lineTo(x, y2);
  }
  canvasContext.stroke();
}

async function runBenchmark() {
  if (!state.wavBlob) {
    setStatus("请先录音或上传音频");
    return;
  }

  const providers = getSelectedProviders();
  if (!providers.length) {
    setStatus("请选择至少一个 ASR");
    return;
  }

  renderRunningRows(providers);
  els.runButton.disabled = true;
  setStatus("正在评测...");

  const formData = new FormData();
  formData.append("file", state.wavBlob, "benchmark.wav");
  formData.append("providers", JSON.stringify(providers));
  formData.append("hotwords", JSON.stringify(getHotwords()));
  formData.append("reference_text", els.referenceInput.value.trim());

  try {
    const response = await fetch(`${API_BASE}/api/asr-benchmark/transcribe`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `评测失败：${response.status}`);
    }
    const data = await response.json();
    renderResults(data.results || [], data.audio || {});
    setStatus("评测完成");
  } catch (error) {
    setStatus(error.message);
  } finally {
    els.runButton.disabled = false;
  }
}

function renderRunningRows(providers) {
  els.resultsBody.innerHTML = "";
  for (const provider of providers) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(provider)}</td>
      <td class="state-running">运行中</td>
      <td></td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td>-</td>
      <td></td>
    `;
    els.resultsBody.append(row);
  }
}

function renderResults(results, audio) {
  els.resultsBody.innerHTML = "";
  if (!results.length) {
    els.resultsBody.innerHTML = '<tr><td colspan="10" class="empty">暂无结果</td></tr>';
    return;
  }

  for (const result of results) {
    const row = document.createElement("tr");
    const isError = Boolean(result.error);
    row.innerHTML = `
      <td>${escapeHtml(result.provider)}</td>
      <td class="${isError ? "state-error" : "state-ok"}">${isError ? "失败" : "完成"}</td>
      <td>${escapeHtml(result.text || "")}</td>
      <td>${formatMs(audio.duration_ms)}</td>
      <td>${formatMs(result.elapsed_ms)}</td>
      <td>${formatScore(result.rtf)}</td>
      <td>${escapeHtml((result.hotword_hits || []).join("、") || "-")}</td>
      <td>${formatScore(result.cer)}</td>
      <td>${formatScore(result.wer)}</td>
      <td>${escapeHtml(result.error || "")}</td>
    `;
    els.resultsBody.append(row);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

els.recordButton.addEventListener("click", () => {
  startRecording().catch((error) => setStatus(error.message));
});

els.stopButton.addEventListener("click", stopRecording);

els.playButton.addEventListener("click", () => {
  els.audioPlayer.currentTime = 0;
  els.audioPlayer.play();
});

els.runButton.addEventListener("click", runBenchmark);
els.refreshProviders.addEventListener("click", () => {
  loadProviders().catch((error) => setStatus(error.message));
});
els.clearResults.addEventListener("click", () => {
  els.resultsBody.innerHTML = '<tr><td colspan="10" class="empty">暂无结果</td></tr>';
});

els.audioFileInput.addEventListener("change", async () => {
  const file = els.audioFileInput.files[0];
  if (!file) return;
  try {
    setStatus("正在处理上传音频...");
    await setAudioBlob(file, file.name);
    setStatus("音频已就绪");
  } catch (error) {
    setStatus(error.message);
  }
});

drawEmptyWaveform(false);
loadProviders().catch((error) => setStatus(error.message));
