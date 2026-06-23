# 项目约定

## 启动与运行

- 唯一代码目录使用 Windows 路径 `C:\AI\Open-LLM-VTuber`。
- 固定使用 Windows Python 环境 `.venv` 启动后端，不再使用 WSL 后端。
- 不要再用 `/mnt/c/AI/Open-LLM-VTuber` + WSL conda 环境启动项目；Qwen3-ASR-GGUF 当前以 Windows DirectML/Vulkan 路径运行。
- 当前常用启动方式是不启动项目自带 Web 前端，只启动 Windows 后端和 Windows TTS：
  1. 在 Windows PowerShell 中启动 TTS：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Windows-TTS.ps1`
  2. 在 Windows PowerShell 中启动后端：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Start-Windows-Backend-Only.ps1`
- 前端开发地址固定为 `http://127.0.0.1:3000/`。
- 后端地址固定为 `http://127.0.0.1:18080/`。
- UE WebSocket 地址固定为 `ws://127.0.0.1:10002`。
- 后端日志在 `logs\backend-only-windows.log` 和 `logs\backend-only-windows.err.log`。
- 不启动项目自带 Web 前端时无需前端日志。
- Windows VoxCPM2 TTS 日志在 `logs\voxcpm2-windows.err.log` 和 `logs\voxcpm2-windows.log`。
- 停止后端：重新运行 `Start-Windows-Backend-Only.ps1` 会先清理旧进程；也可结束 `logs\backend-only-windows.pid` 记录的进程树。
- 停止 Windows TTS：结束监听 `50005` 的 Windows 进程，或重新运行 `Start-Windows-TTS.ps1`，脚本会先清理旧监听进程。

## 当前语音链路

- 当前低延迟 TTS 优先使用 `voxcpm2_tts`，后端是 VoxCPM2 NanoVLLM HTTP 服务。
- 当前使用 Windows 版 VoxCPM2 项目：`C:\AI\voxcpm2-nanovllm-win-venv`。
- Windows VoxCPM2 服务监听 `0.0.0.0:50005`，Windows 本机可用 `http://127.0.0.1:50005` 检查。
- Windows 后端访问 Windows VoxCPM2 时使用 `conf.yaml` 中的 `http://127.0.0.1:50005`。
- 用 `curl http://127.0.0.1:50005/health` 在 Windows 侧检查 VoxCPM2 服务状态。
- 声音克隆用到的 prompt 音频路径只保留在本地配置里，不要提交私有 WAV 文件。
- ASR 固定使用 `qwen3_asr_gguf`，代码通过子仓库 `Qwen3-ASR-GGUF` 引用。
- Qwen3-ASR-GGUF 模型文件不提交，放在 `Qwen3-ASR-GGUF\model`。
- ASR 通过 Qwen3-ASR-GGUF 的 Python 接口常驻加载模型，不使用 `transcribe.exe` CLI。

## LLM 行为

- DeepSeek 通过 OpenAI-compatible LLM 适配器接入。
- DeepSeek V4 语音对话需要在本地 `conf.yaml` 里保持 `thinking: disabled`，用于降低首句延迟。
- `conf.yaml` 不应直接写 API key；真实 key 放在 `.env`，`.env` 被忽略，不要提交。
- 当前角色提示词是中文语音友好的“小智”风格：短、直接、口语化，适合 TTS 播报。
- LLM 输出必须可朗读。纯标点、只有省略号、空白或只有表情时，应兜底为一句短的可播报文本。
- 单人会话的 `text-input` 支持重启式追加：同一 `client_uid` 已有未完成 `process_single_conversation` 时，新输入会取消旧任务并立即重启；已经写入 agent memory 的前序用户输入作为独立 `role=user` 消息保留，最终只让数字人生成一次回复。

## 延迟调试

- 对话耗时日志统一使用 `PERF conversation` 前缀。
- 关键事件包括 `input_ready`、`first_agent_output`、`first_tts_task_queued`、`first_tts_audio_generated`、`first_audio_sent`。
- 发送给 UE 的 audio 消息包含 `ServerTurnId` 和 `ServerElapsedMs`，用于查看服务端首段音频耗时。
- ASR 会默认保存现场音频样本和识别结果到 `reports/asr_captures/YYYYMMDD/`，每次生成一组 `.wav` + `.json`。
- ASR 样本 JSON 包含 provider、转写文本、RTF、RMS/峰值音量、来源和附加 metadata，便于复现现场环境下的音量/清晰度问题。
- 如需关闭 ASR 样本保存，设置环境变量 `ASR_CAPTURE_ENABLED=0`；如需改保存目录，设置 `ASR_CAPTURE_DIR`。
- 对已保存样本做多 ASR 回放对比：`python scripts/asr_replay_captures.py reports/asr_captures --providers sherpa_onnx_asr,groq_whisper_asr`。

## 验证要求

- Python 代码改动后，对触碰的模块运行 `python -m py_compile`。
- 运行链路改动后，用 `Start-Windows-Backend-Only.ps1` 重启，并确认后端 ready。
