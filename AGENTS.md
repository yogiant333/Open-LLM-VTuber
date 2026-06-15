# 项目约定

## 启动与运行

- 在 WSL 里使用 `./start_wsl.sh` 重启项目。
- 前端开发地址固定为 `http://127.0.0.1:3000/`。
- 后端地址固定为 `http://127.0.0.1:18080/`。
- 后端日志在 tmux 会话 `open-llm-vtuber`。
- 前端日志在 tmux 会话 `open-llm-vtuber-frontend`。

## 当前语音链路

- 当前低延迟 TTS 优先使用 `voxcpm2_tts`，后端是 VoxCPM2 NanoVLLM HTTP 服务。
- VoxCPM2 服务地址预期为 `http://127.0.0.1:50005`。
- 用 `curl http://127.0.0.1:50005/health` 检查 VoxCPM2 服务状态。
- 声音克隆用到的 prompt 音频路径只保留在本地配置里，不要提交私有 WAV 文件。

## LLM 行为

- DeepSeek 通过 OpenAI-compatible LLM 适配器接入。
- DeepSeek V4 语音对话需要在本地 `conf.yaml` 里保持 `thinking: disabled`，用于降低首句延迟。
- `conf.yaml` 是本地配置并被忽略，可能包含 API key，不要强制加入 git。
- 当前角色提示词是中文语音友好的“小智”风格：短、直接、口语化，适合 TTS 播报。
- LLM 输出必须可朗读。纯标点、只有省略号、空白或只有表情时，应兜底为一句短的可播报文本。
- 单人会话的 `text-input` 支持重启式追加：同一 `client_uid` 已有未完成 `process_single_conversation` 时，新输入会取消旧任务并立即重启；已经写入 agent memory 的前序用户输入作为独立 `role=user` 消息保留，最终只让数字人生成一次回复。

## 延迟调试

- 对话耗时日志统一使用 `PERF conversation` 前缀。
- 关键事件包括 `input_ready`、`first_agent_output`、`first_tts_task_queued`、`first_tts_audio_generated`、`first_audio_sent`。
- 发送给 UE 的 audio 消息包含 `ServerTurnId` 和 `ServerElapsedMs`，用于查看服务端首段音频耗时。

## 验证要求

- Python 代码改动后，对触碰的模块运行 `python -m py_compile`。
- 运行链路改动后，用 `./start_wsl.sh` 重启，并确认前端和后端都 ready。
