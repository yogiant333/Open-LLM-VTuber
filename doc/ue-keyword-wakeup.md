# 浏览器音频链路 KWS 与 UE 数字人状态接入方案

本文档记录当前项目中“关键字唤醒 / 唤醒词 / wake word”相关能力的现状，以及在浏览器 `/client-ws` 音频链路中接入 KWS、再向 UE 数字人同步状态时建议采用的协议和实现边界。

## 结论

当前后端没有完整的浏览器音频链路 KWS 门控能力。

已有能力包括：

- ASR 配置里有 sherpa-onnx 的 `hotwords_file`、`hotwords_score` 等“热词”参数。
- 前端和后端已有麦克风、VAD、ASR、文本输入、对话触发链路。
- 后端已有 Fay 兼容 UE WebSocket 服务，监听 `ws://127.0.0.1:10002`。
- UE 服务已经能向 UE 下发 `question`、`log`、`text`、`audio`、`suggestions`。

缺失能力包括：

- 没有独立的 wake word / KWS 状态机。
- 没有“未唤醒时只监听唤醒词，唤醒后才进入 ASR/LLM”的门控逻辑。
- UE WebSocket 入站消息目前只更新 `Username` 和 `Output` 元数据，没有处理 UE 发来的唤醒事件。
- 没有 KWS 命中后向前端和 UE 广播唤醒状态的桥接事件。

因此，README 中提到的 voice wake-up 更像上游项目能力描述或未来目标；在当前 UE 服务链路里，不能视为已经可用。

## 相关代码位置

UE WebSocket 服务：

- `src/open_llm_vtuber/ue_avatar_server.py`

当前行为：

- 启动 `10002` WebSocket。
- 保存已连接 UE 客户端的 `Username` 和 `Output`。
- 后端向 UE 广播 Fay 兼容消息。
- 对 UE 入站 JSON 的处理仅限元数据更新。

UE 下行协议封装：

- `src/open_llm_vtuber/ue_avatar_protocol.py`

当前支持：

- `Data.Key=question`
- `Data.Key=log`
- `Data.Key=text`
- `Data.Key=audio`
- `Data.Key=suggestions`

浏览器运行时 WebSocket：

- `src/open_llm_vtuber/websocket_handler.py`

当前支持：

- 初始连接后向前端发送 `{"type":"control","text":"start-mic"}`。
- 接收 `mic-audio-data`、`raw-audio-data`、`mic-audio-end`、`text-input` 等事件。
- `raw-audio-data` 走 VAD，检测语音段后触发 `mic-audio-end`。

对话触发：

- `src/open_llm_vtuber/conversations/conversation_handler.py`

当前支持：

- `text-input` 直接进入文本对话。
- `mic-audio-end` 将缓存音频送 ASR，再进入对话。
- 单人会话支持重启式追加，新输入会取消旧任务并重启。

ASR 热词配置：

- `src/open_llm_vtuber/asr/sherpa_onnx_asr.py`
- `config_templates/conf.default.yaml`
- `config_templates/conf.ZH.default.yaml`

注意：ASR 热词不是唤醒词。它只能提高某些词在转写结果中的权重，不能替代低延迟唤醒检测，也不能阻止未唤醒状态下进入对话。

## 目标行为

面向 UE 端服务，建议目标行为是：

1. 浏览器 `/client-ws` 持续向后端发送待机音频帧。
2. 后端在同一个 audio session 中运行 KWS。
3. 命中唤醒词后，后端记录并广播 `ue-wakeup` 状态。
4. 后端基于近似命中时刻和 ring buffer 保留连续音频，不重新开始录音。
5. 用户说完问题后，现有 ASR、LLM、TTS、UE 下行动作链路继续复用。

推荐把“唤醒词检测”合并进后端现有语音入口，而不是做成独立唤醒事件。原因是用户可能连续说“唤醒词 + 提问”，如果先发唤醒事件再开始录音，容易漏掉提问开头。

## 建议音频入口协议

推荐优先使用浏览器 `/client-ws` 作为统一音频入口。

不要新增与 `raw-audio-data` 并行的 `kws-audio-data`。KWS 开启时，前端只发送一种待机音频帧，后端 `AudioSession` 统一处理 KWS/VAD/ASR：

- 首选复用现有 `raw-audio-data`，但在 KWS 模式下先进入 `AudioSession`，不再直接走旧 VAD 触发 `mic-audio-end`。
- 如果需要协议改名，可升级为 `audio-input-frame`；不要同时发送新旧两种音频帧。
- 高频音频帧必须跳过通用消息缓存、历史和逐帧普通日志。

统一音频帧建议格式：

```json
{
  "type": "raw-audio-data",
  "audio_format": "pcm_f32le",
  "sample_rate": 16000,
  "channels": 1,
  "frame_ms": 40,
  "audio": [0.01, -0.02, 0.03]
}
```

格式约束：单声道、16 kHz、归一化 float32 JSON 数组；如果后续改为二进制或 base64，则统一 little-endian int16 PCM。帧长固定为 20ms、40ms 或 100ms，首版建议 40ms。

后端内部处理：

```text
raw-audio-data / audio-input-frame
  -> AudioSession ring buffer
  -> idle: KWS 检测
  -> listening: VAD 收集问题音频
  -> ASR 按原文进入对话
```

UE 的 `10002` WebSocket 继续作为数字人控制通道，不作为第一版 KWS 入站通道。

## UE 数字人入站协议

UE 连接仍然使用：

```text
ws://127.0.0.1:10002
```

连接后保留现有元数据消息：

```json
{
  "Username": "User",
  "Output": true
}
```

第一版不要求 UE 通过 `10002` 发送唤醒事件。`10002` 继续接收后端下发的字幕、音频、推荐问题和状态即可。

## UE 麦克风与 KWS 控制协议

UE 麦克风上行使用后端 FastAPI `/client-ws`：

```text
wss://10.0.2.155:18080/client-ws
```

连续麦克风流继续发送：

```json
{
  "type": "raw-audio-data",
  "audio": [0.0, 0.01, -0.02],
  "sample_rate": 16000,
  "channels": 1,
  "audio_format": "pcm_f32le",
  "frame_ms": 40
}
```

KWS 运行态由 UE 动态控制。查询：

```json
{
  "type": "kws-config-request"
}
```

启用或调整：

```json
{
  "type": "kws-config-update",
  "enabled": true,
  "wake_words": ["小智小智"],
  "frame_ms": 40,
  "pre_roll_ms": 600,
  "cooldown_seconds": 2.0,
  "listen_timeout_seconds": 10.0,
  "active_timeout_seconds": 120.0,
  "keywords_score": 1.0,
  "keywords_threshold": 0.25
}
```

服务端返回并广播：

```json
{
  "type": "kws-config-state",
  "success": true,
  "kws_config": {
    "enabled": true,
    "requested_enabled": true,
    "model_ready": true,
    "vad_ready": true,
    "sample_rate": 16000,
    "channels": 1,
    "audio_format": "pcm_f32le",
    "frame_ms": 40
  }
}
```

模型路径、`tokens`、`keywords_file` 保留在服务端配置里，UE 不下发本地路径。`wake_words` 主要用于业务展示；实际可命中的关键词由服务端 `keywords_file` 决定。ASR 结果按原文进入对话，后端不额外过滤唤醒词。

## 建议后端广播协议

后端 KWS 命中后，建议向所有 `/client-ws` 前端连接广播：

```json
{
  "type": "ue-wakeup",
  "username": "User",
  "keyword": "小智小智",
  "confidence": 0.92,
  "source": "client-ws"
}
```

随后发送状态控制消息：

```json
{
  "type": "control",
  "text": "wakeup-detected"
}
```

注意：不建议只发送 `start-mic` 再开始录音，因为此时用户可能已经在说问题。前端应在待机时就持续发送 KWS 音频帧。

如果希望 UE 端唤醒后由后端主动提示用户，也可以额外向 UE 下发：

```json
{
  "Topic": "human",
  "Data": {
    "Key": "log",
    "Value": "我在，请说。"
  },
  "Username": "User"
}
```

这条消息只用于 UI/状态提示，不建议进入 TTS，避免唤醒后抢占用户说话窗口。

## 建议状态机

最小可用状态机：

```text
idle
  -> wakeup_detected
  -> listening
  -> processing
  -> speaking
  -> listening
  -> idle
```

状态说明：

- `idle`：未唤醒，只运行 KWS，不进入 ASR/LLM。
- `wakeup_detected`：命中唤醒词，后端广播状态。
- `listening`：继续收集用户问题音频；唤醒后一段活跃窗口内的后续问题不需要重复说唤醒词。
- `processing`：ASR/LLM/TTS 正在处理。
- `speaking`：UE 正在播放后端下发音频。
- `listening`：UE 播放完成并且前端播放队列清空后，继续等待用户追问。
- `idle`：`active_timeout_seconds` 内没有新的用户语音，回到等待唤醒。

`backend-synth-complete` 只表示后端合成和发送完成，不表示 UE 已播放完成。播放完成后应回到 `listening`，继续保持连续对话；如果 `active_timeout_seconds` 内没有新的用户语音，再退回 `idle`，下次需要重新唤醒。如果后续 UE 直接上报播放状态，也需要提供等价 ack。

第一版应先实现“统一音频入口 + KWS/ASR 门控”，避免连续提问漏字。后续如果需要展厅级稳定性，再加超时、打断、误唤醒取消等规则。

## 实现建议

建议分三步实现。

第一步：补后端 KWS audio session。

- 在 `WebSocketHandler` 中把 `raw-audio-data` 或升级后的 `audio-input-frame` 分流到 audio fast path。
- KWS 开启时，禁止同一 client 同时走旧 `_handle_raw_audio_data()` VAD 路径和新 `AudioSession` 路径。
- 为每个 `client_uid` 维护 `deque` ring buffer 或预分配循环数组，不要用 `np.append` 做长期流式缓冲。
- KWS 命中后记录近似命中时刻，不要求精确唤醒词结束 sample。
- 将近似命中时刻附近的连续音频交给 VAD/ASR，ASR 文本按原文进入对话。
- 向 `/client-ws` 前端广播 `ue-wakeup` 和 `control/wakeup-detected`。

第二步：增加前端或控制台展示。

- 收到 `ue-wakeup` 后显示唤醒状态。
- 可选：短暂显示“已唤醒 / 请说话”。
- 不改变现有聊天、字幕、音频播放逻辑。

第三步：按需要增加门控。

- 未唤醒时只运行 KWS，不进入 ASR/LLM。
- 唤醒后设置监听超时，例如 8 到 15 秒。
- 用户说完或超时后回到 `idle`。
- AI 播放中收到新唤醒或语音时，复用现有 `interrupt-signal` 打断逻辑。

## 不建议的方案

不建议只依赖 ASR 热词：

- 热词会影响转写结果，不会降低持续 ASR 成本。
- 热词无法天然提供“唤醒前不进入对话”的状态门控。
- 热词误识别后仍可能触发完整对话链路。

不建议让 LLM 判断是否被唤醒：

- 延迟高。
- 成本高。
- 会把噪音和非目标语音送入 LLM。
- 展厅或 UE 常驻场景下容易产生误触发。

不建议把 UE 下行 `suggestions` 当作唤醒：

- `suggestions` 是推荐问题 UI，不进入 TTS，也不是输入事件。
- 唤醒是 UE/用户到后端的入站控制事件，两者方向不同。

## 验证要点

实现后至少验证：

- UE 连接 `ws://127.0.0.1:10002` 后仍能正常接收 `text/audio`。
- 前端发送统一音频帧后，后端 KWS 能检测唤醒词。
- `/client-ws` 前端收到 `ue-wakeup`。
- `ue-wakeup.source` 为 `client-ws` 或 `kws`，不是 `ue`。
- `/client-ws` 前端随后收到 `control/wakeup-detected`。
- 连续说“小智小智，今天负荷怎么样”时，ASR 不漏掉“今天”，且后端不额外删除唤醒词文本。
- 未唤醒时旧 VAD 不会触发 `mic-audio-end`。
- 后端收到 `frontend-playback-complete` / 播放队列清空通知后才回到 `idle`。
- 不影响现有 `Username`、`Output` 元数据更新。
- 不影响现有 UE 音频消息中的 `Data.Value` 和 `Data.HttpValue`。

Python 代码改动后，按项目约定至少运行：

```text
python -m py_compile src/open_llm_vtuber/ue_avatar_server.py src/open_llm_vtuber/websocket_handler.py
```

Windows HTTPS 运行链路改动后，用当前 Windows 启动入口：

```text
Start-Windows-HTTPS-With-WSL-TTS.bat
```

重启并确认前端和后端都 ready。
