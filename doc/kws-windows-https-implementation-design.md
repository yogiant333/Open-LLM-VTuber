# Windows HTTPS 启动模式下的 KWS 实现设计

本文档针对当前启动入口：

```text
D:\AI\Open-LLM-VTuber\Start-Windows-HTTPS-With-WSL-TTS.bat
```

说明实际运行环境，并给出 KWS（Keyword Spotting，关键字唤醒）的实现设计。本文不考虑独立 KWS 服务，KWS 必须合并进现有语音链路，避免用户连续说“唤醒词 + 提问”时丢字。

## 当前启动环境

`Start-Windows-HTTPS-With-WSL-TTS.bat` 只是 Windows 批处理包装器，实际执行：

```text
Start-Windows-HTTPS-With-WSL-TTS.ps1
```

该 PowerShell 脚本启动两个主服务：

| 服务 | 运行环境 | 启动方式 | 默认地址 |
| --- | --- | --- | --- |
| 后端 FastAPI | Windows 本机 | `set UV_PROJECT_ENVIRONMENT=.venv&& uv run uvicorn run_server:create_app --factory ...` | `https://10.0.2.155:18080/` |
| 前端 Vite | Windows 本机 | `npm run dev:web -- --host 0.0.0.0 --force` | `https://10.0.2.155:3000/` |
| UE WebSocket | 后端进程内 | `ue_avatar_server.start()` | `ws://10.0.2.155:10002` |
| VoxCPM2 TTS | WSL，单独启动 | `Start-WSL-TTS.ps1` | `http://127.0.0.1:50005/health` |

关键点：

- 后端不是 WSL 进程，而是 Windows 本机进程。
- 后端 Python 环境由 `uv` 管理，并显式使用 `.venv`。
- 后端内置 KWS 依赖必须安装到 `.venv`。
- TTS 才在 WSL 里跑，通过 HTTP 暴露给 Windows 后端。
- 后端日志在 `logs/backend-windows.log` 和 `logs/backend-windows.err.log`。

## 设计结论

KWS 和 ASR 应该合并到同一条音频链路里。

原因是用户很可能连续说：

```text
小智小智，今天负荷怎么样？
```

如果 KWS 只触发一个“已唤醒”事件，然后再让前端开始录音，用户问题的开头已经说过去了。正确设计是：

```text
同一条麦克风音频流
  -> 后端 audio session
  -> ring buffer
  -> KWS 检测唤醒词
  -> 命中后切换为 listening
  -> 基于近似命中时刻保留连续音频
  -> VAD 判断用户问题结束
  -> ASR 按原文转写问题音频
  -> LLM/TTS
  -> UE text/audio
```

也就是说，KWS 和 ASR 可以用不同模型，但不能各自监听不同 WebSocket 或不同录音生命周期。它们必须共享同一个音频入口、同一个缓冲区和同一个会话状态。

## 当前能力差距

已有能力：

- 浏览器前端可采集麦克风。
- `/client-ws` 已有 `raw-audio-data`、`mic-audio-data`、`mic-audio-end`。
- 后端已有 VAD 和 ASR。
- 当前 ASR 是 `sherpa_onnx_asr` + `sense_voice`。
- 后端已有 UE WebSocket，负责向 UE 下发 `question`、`text`、`audio`、`suggestions`。

缺失能力：

- 没有 sherpa-onnx KWS 模型封装。
- 没有每个 `client_uid` 的 KWS/audio session。
- 没有唤醒词命中后的 ring buffer 截取逻辑。
- 没有“未唤醒不进 ASR/LLM，已唤醒才收集问题”的门控。
- 没有 `ue-wakeup` / `wakeup-detected` 状态广播。

ASR 热词不是 KWS。热词只影响识别偏好，不能替代唤醒检测和状态门控。

## 推荐模型

推荐使用 sherpa-onnx KWS 模型：

```text
sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20
```

原因：

- 支持中文和英文。
- 适合“小智小智”这类中文唤醒词。
- open vocabulary KWS，可以通过 `keywords_file` 自定义关键词，不需要为每个关键词重新训练。
- int8 ONNX 模型适合 Windows 本机 CPU 常驻。

备选：

| 模型 | 场景 |
| --- | --- |
| `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20` | 首选，中英混合 |
| `sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01` | 中文 |
| `sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01` | 英文 |

## 音频入口选择

推荐优先使用浏览器 `/client-ws` 作为统一音频入口。

原因：

- 当前启动模式下前端是 HTTPS，浏览器麦克风权限可用。
- 现有代码已经有 `/client-ws` 会话、`client_uid`、VAD 和对话触发。
- 不需要 Windows 后端进程直接抢占麦克风。
- KWS 命中后可以继续使用同一条音频流，不会丢失连续提问。

不要新增一条与 `raw-audio-data` 并行的 `kws-audio-data` 音频流。KWS 开启时，前端只发送一种待机音频帧，后端 `AudioSession` 独占处理该 client 的流式音频：

- 优先复用现有 `raw-audio-data`，但在 `kws_config.enabled=true` 时改变后端处理路径：先进入 `AudioSession`，由状态机决定只跑 KWS 还是进入 VAD/ASR。
- 如果需要避免旧命名歧义，可把协议升级为 `audio-input-frame`，但同一时刻仍只能有一种麦克风帧入口。
- 不允许同时发送 `raw-audio-data` 和 `kws-audio-data` 两路音频，否则未唤醒状态下旧 VAD 仍可能触发 `mic-audio-end`。

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

音频格式必须在前后端转换层写死并校验：

- 单声道。
- 16 kHz。
- 推荐 WebSocket JSON 数组使用归一化 `float32`，范围 `[-1.0, 1.0]`；如果改成二进制帧或 base64，则统一为 little-endian `int16 PCM`。
- 每帧 20ms、40ms 或 100ms 之一，首版建议 40ms，在延迟和消息量之间折中。
- 后端 KWS/VAD/ASR 前统一转换为 numpy `float32` 单声道 16k，避免 `raw-audio-data`、`mic-audio-data` 各自保留不同数据形态。

后端内部统一处理：

```text
raw-audio-data / audio-input-frame
  -> AudioSession.append_frame()
  -> ring buffer
  -> idle: KWS detector only
  -> wake state machine
  -> listening: VAD/ASR collection
```

高速音频帧必须绕开通用 `message_handler.handle_message(client_uid, data)` 的缓存、历史和普通日志路径。`/client-ws` 收到音频帧后应先按 `type` 分流到专用 fast path，只记录采样率、帧数、状态切换、KWS 命中等聚合事件，不能逐帧写普通日志。

UE 的 `10002` WebSocket 继续作为数字人协议，不作为第一版用户麦克风音频入口。UE 只接收后端下发的状态、字幕和音频。

## 状态机

每个 `client_uid` 维护一个 audio session：

```text
idle
  -> wakeup_detected
  -> listening
  -> processing
  -> speaking
  -> idle
```

状态说明：

- `idle`：持续接收音频，只跑 KWS，不进入 ASR/LLM。
- `wakeup_detected`：KWS 命中，记录近似命中时刻和关键词，广播状态。
- `listening`：继续收集用户问题音频，同时跑 VAD；唤醒后一段活跃窗口内的后续问题不需要重复说唤醒词。
- `processing`：VAD 判定问题结束，把问题音频送 ASR/LLM/TTS。
- `speaking`：UE 播放后端下发音频。
- UE 确认播放完成并且前端播放队列清空后回到 `listening`，继续等待用户追问。

关键规则：

- KWS 命中后，不重新开一条录音。
- 不依赖“精确唤醒词结束 sample”。sherpa-onnx KWS 提供关键词命中能力，但中文唤醒词边界不应作为硬切分点。
- ASR 输入使用“近似命中时刻 + ring buffer pre-roll”裁剪，ASR 文本按原文进入对话。
- 需要保留少量 pre-roll，例如 300 到 800ms，防止 KWS 边界偏晚导致漏字。
- 如果唤醒后 `active_timeout_seconds` 内没有有效语音，回到 `idle`，下次需要重新说唤醒词。
- AI 播放中如检测到用户说话，继续复用现有 interrupt 逻辑。
- `backend-synth-complete` 只表示后端合成和发送完成，不表示 UE 已播放完成；不能用它直接把状态切回 `idle`。
- `speaking -> listening` 必须以 `frontend-playback-complete` / 播放队列清空通知为准。UE 播放链路如果绕过浏览器，也需要补等价的播放完成 ack。

## 后端模块设计

建议新增：

```text
src/open_llm_vtuber/kws/
  __init__.py
  kws_interface.py
  sherpa_onnx_kws.py
  audio_session.py
  wakeup_event.py
```

职责：

- `kws_interface.py`：统一接口，例如 `accept_waveform()`、`reset()`。
- `sherpa_onnx_kws.py`：封装 sherpa-onnx KeywordSpotter。
- `audio_session.py`：维护 ring buffer、状态机、KWS/VAD/ASR 分流。
- `wakeup_event.py`：定义唤醒事件结构。

需要改动的现有文件：

- `websocket_handler.py`
  - 将 `raw-audio-data` 或升级后的 `audio-input-frame` 接入 audio fast path。
  - KWS 开启时禁止同一 client 同时走旧 `_handle_raw_audio_data()` VAD 路径和新 `AudioSession` 路径。
  - 高频音频帧跳过通用 message cache、历史和逐帧普通日志。
  - 为每个 `client_uid` 创建/清理 audio session。
  - KWS 命中后广播 `ue-wakeup` 和 `control/wakeup-detected`。
- `conversations/conversation_handler.py`
  - 支持从 audio session 交付的“已裁剪问题音频”触发 `mic-audio-end` 等价流程。
- `server.py`
  - 初始化 KWS 模型配置。
  - 服务退出时释放 KWS/audio session 资源。
- `routes.py`
  - 可选新增 `GET /api/runtime/kws-status`，只做状态查询，不作为唤醒入口。

UE 相关：

- `ue_avatar_protocol.py`
  - 可新增 `send_wakeup_status()`，向 UE 下发 `Data.Key=wakeup_status` 或 `Data.Key=log`。
- `ue_avatar_server.py`
  - 第一版不需要处理 UE 入站唤醒事件。

实现约束：

- `received_data_buffers` 不能继续用 `np.append` 做常驻流缓冲。KWS 待机是长期流式监听，必须改用 `deque` ring buffer 或预分配循环数组，避免每帧复制整段历史音频。
- 只在 `listening` 或短时间问题收集窗口里生成用于 ASR 的连续数组。

## 配置设计

建议在 `conf.yaml` 增加：

```yaml
kws_config:
  enabled: false
  provider: sherpa_onnx_kws
  wake_words:
    - 小智小智
  sample_rate: 16000
  channels: 1
  audio_format: pcm_f32le
  frame_ms: 40
  pre_roll_ms: 600
  cooldown_seconds: 2.0
  listen_timeout_seconds: 10.0
  active_timeout_seconds: 120.0
  sherpa_onnx_kws:
    encoder: ./models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx
    decoder: ./models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/decoder-epoch-13-avg-2-chunk-16-left-64.onnx
    joiner: ./models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx
    tokens: ./models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/tokens.txt
    keywords_file: ./models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/keywords.txt
    keywords_score: 1.0
    keywords_threshold: 0.25
    num_threads: 1
    provider: cpu
```

说明：

- `enabled` 默认 `false`，避免升级后自动改变录音行为。
- `wake_words` 是业务唤醒词。
- `keywords_file` 是 sherpa-onnx 实际读取的 token 化关键词文件。
- `sample_rate`、`channels`、`audio_format`、`frame_ms` 是协议约束，前端发送和后端转换层必须一致。
- `pre_roll_ms` 用于保护“唤醒词后立刻提问”的开头。
- `cooldown_seconds` 防止一次唤醒重复触发。
- `listen_timeout_seconds` 保留为兼容字段。
- `active_timeout_seconds` 控制唤醒后连续对话窗口，默认 120 秒无用户语音后回到 `idle`。
- 模型路径、`tokens`、`keywords_file` 仍由服务端配置控制；UE 不应通过 websocket 下发任意本地路径。
- `enabled` 是默认启动状态，运行中可由 UE 通过 `/client-ws` 动态覆盖。

## UE 动态 KWS 控制

UE 麦克风连续流和 KWS 控制都走后端 FastAPI `/client-ws`，不是 UE 数字人 `10002` 下行通道。

UE 可查询当前 KWS 运行态：

```json
{
  "type": "kws-config-request"
}
```

后端返回：

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

UE 可动态启停和调整安全运行态参数：

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

限制：

- `sample_rate` 固定 `16000`，`channels` 固定 `1`，`audio_format` 固定 `pcm_f32le`。
- `wake_words` 用于业务展示；实际 KWS 可命中的词仍取决于服务端 `keywords_file`。
- `kws-config-update` 成功后后端会向所有 `/client-ws` 连接广播最新 `kws-config-state`。
- 启用时若模型文件缺失或 VAD 未就绪，后端返回 `success=false`，不会创建 `AudioSession`。

## 关键词文件生成

原始关键词文件：

```text
小智小智 @小智小智
你好小明 @你好小明
```

目标 token 文件示意：

```text
x iǎo zh ì x iǎo zh ì @小智小智
n ǐ h ǎo x iǎo zh ì @你好小智
```

实现时优先使用 sherpa-onnx 的 `text2token` 工具生成，不要在批量配置中手写拼音 token；单个默认词可在模型目录保留已审查的生成结果。

## 前端行为

前端需要新增一个“待机监听”模式：

1. 页面加载并获得麦克风权限。
2. 在 `idle` 状态持续发送统一音频帧到 `/client-ws`，不要同时发送旧 VAD 帧和 KWS 帧。
3. 收到 `ue-wakeup` 或 `control/wakeup-detected` 后显示已唤醒状态。
4. 不重新打开麦克风，不重新开始录音。
5. 收到后端 `conversation-chain-start`、`conversation-chain-end` 等现有状态后更新 UI。

隐私提示：

- 因为待机时也会持续发送音频给后端，前端 UI 应明确显示“正在监听唤醒词”。

## UE 行为

UE 数字人下行仍连接：

```text
ws://10.0.2.155:10002
```

UE 继续接收：

- `Data.Key=text`
- `Data.Key=audio`
- `Data.Key=suggestions`
- `Data.Key=log`

UE 麦克风上行使用后端 `/client-ws`：

```text
wss://10.0.2.155:18080/client-ws
```

连续监听时发送：

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

可新增状态消息：

```json
{
  "Topic": "human",
  "Data": {
    "Key": "wakeup_status",
    "Value": "wakeup_detected",
    "Keyword": "小智小智",
    "Source": "client-ws"
  },
  "Username": "User"
}
```

UE 不需要在第一版做 KWS，也不需要向后端发 `wakeup`。

## Windows 环境依赖

当前后端使用 `.venv`，验证依赖时必须使用同款环境：

```text
set UV_PROJECT_ENVIRONMENT=.venv&& uv run python -c "import sherpa_onnx"
```

如果 KWS 只处理浏览器传来的音频帧，后端不需要直接访问麦克风，也就不需要 `sounddevice`。

如果未来改成后端直接采集麦克风，才需要额外评估：

```text
sounddevice
```

## 启动脚本设计

不新增独立 KWS 启动脚本。

KWS 模型随 Windows 后端配置加载；默认启停由 `conf.yaml` 的 `kws_config.enabled` 决定，运行中可由 UE 通过 `/client-ws` 的 `kws-config-update` 覆盖：

```text
Start-Windows-HTTPS-With-WSL-TTS.bat
  -> Start-Windows-HTTPS-With-WSL-TTS.ps1
  -> uvicorn run_server:create_app
  -> WebSocketServer.initialize()
  -> 初始化 ASR/TTS/VAD
  -> UE /client-ws 可动态初始化或关闭 KWS
```

不建议增加第二个 KWS 进程，也不建议用启动脚本参数承担运行时控制；运行态控制应走 `/client-ws`。

## 验证计划

环境验证：

```text
set UV_PROJECT_ENVIRONMENT=.venv&& uv run python -c "import sherpa_onnx"
```

模型验证：

```text
sherpa-onnx-keyword-spotter --encoder ... --decoder ... --joiner ... --tokens ... --keywords-file ...
```

链路验证：

1. 启动 `Start-Windows-HTTPS-With-WSL-TTS.bat`。
2. 打开 `https://10.0.2.155:3000/`。
3. 授权麦克风。
4. 前端进入“监听唤醒词”状态。
5. 连续说：“小智小智，今天负荷怎么样？”
6. 后端日志出现 KWS 命中。
7. 前端收到 `ue-wakeup`，其中 `source` 为 `client-ws` 或 `kws`，不是 `ue`。
8. ASR 转写结果按原文进入对话，后端不额外剥离“小智小智”。
9. LLM/TTS 正常回复。
10. UE 收到 `text/audio` 并播放。

回归验证：

- KWS 关闭时，原有文本输入和语音输入仍可用。
- UE `Data.Value` 本地 WAV 路径不变。
- UE `Data.HttpValue` 下载 URL 不变。
- 单人会话重启式追加逻辑不变。

## 风险与处理

连续提问漏字：

- 用同一条音频流和 ring buffer 解决。
- 设置 `pre_roll_ms`，不要只从 KWS 命中时刻之后截音频。
- ASR 文本不做唤醒词过滤，避免后处理误删用户原话。

误唤醒：

- 调整 `keywords_threshold` 和 `keywords_score`。
- 加 `cooldown_seconds`。
- 唤醒后若 VAD 没检测到有效语音，自动回到 `idle`。

持续监听带宽：

- 使用固定的 16kHz 单声道小帧，JSON 传输用归一化 float32，二进制/base64 传输用 int16 PCM。
- 可以只在 KWS 模式发送必要音频，不发送图片或其他大 payload。

麦克风权限：

- 当前入口是 HTTPS，浏览器麦克风权限可用。
- 前端必须明确显示监听状态。

Windows 依赖：

- 所有后端依赖都装在 `.venv`。
- 不用系统 Python 判断依赖是否存在。

## 建议结论

当前启动模式下，最终方案应为：

1. KWS 内置到 Windows 后端。
2. 浏览器 `/client-ws` 作为统一音频入口。
3. 前端持续发送待机音频帧。
4. 后端 audio session 同时管理 ring buffer、KWS、VAD 和 ASR 门控。
5. KWS 命中后不重新录音，而是用近似命中时刻和 pre-roll 保护连续提问不漏字。
6. UE 继续只负责数字人状态、字幕、音频播放。
