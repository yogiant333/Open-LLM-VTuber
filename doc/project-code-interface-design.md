# Open-LLM-VTuber 项目代码接口设计

本文面向想阅读和二次开发本项目的人，重点解释代码里的“接口边界”：进程如何启动，前后端如何通信，后端内部如何把 ASR、LLM Agent、TTS、Live2D/数字人渲染串起来，以及新增能力时应该改哪些层。

## 1. 总体架构

项目由三个主要运行面组成：

| 运行面 | 主要目录 | 责任 |
| --- | --- | --- |
| Python 后端 | `run_server.py`, `src/open_llm_vtuber/` | FastAPI 服务、WebSocket 会话、ASR/Agent/TTS 编排、静态资源、UE 数字人桥接 |
| React 前端 | `frontend/src/renderer/src/` | Web/Electron 渲染层、Live2D 画布、聊天 UI、音频采集播放、WebSocket 协议适配 |
| Electron 桌面壳 | `frontend/src/main/`, `frontend/src/preload/` | 窗口模式/桌宠模式、托盘菜单、系统 IPC、屏幕捕获权限 |

核心数据流：

```text
用户文本/麦克风/图片
  -> React hooks
  -> ws://127.0.0.1:18080/client-ws
  -> WebSocketHandler
  -> ServiceContext
  -> ASR -> Agent -> TTS
  -> WebSocket audio/control/full-text 消息
  -> 前端播放音频、驱动 Live2D/LiveTalking/UE5
```

默认开发启动：

| 服务 | 命令 | 地址 |
| --- | --- | --- |
| 后端 | `uv run run_server.py` | `http://127.0.0.1:18080` |
| 前端 Web | `cd frontend && npm run dev:web -- --host 127.0.0.1 --force` | `http://127.0.0.1:3000` |

当前本机运行时，仓库根目录固定使用 Windows 目录在 WSL 中的挂载路径：

```bash
cd /mnt/c/AI/Open-LLM-VTuber
./start_wsl.sh
```

WSL 脚本入口是仓库根目录的 `start_wsl.sh`，它用 `tmux` 分别托管后端和前端。不要从 `/home/yy/AI/Open-LLM-VTuber` 启动服务，避免运行代码和 Windows 工作区代码不同步。

## 2. 入口与生命周期

### 2.1 后端入口

`run_server.py` 是后端主入口。

关键函数：

| 函数 | 作用 |
| --- | --- |
| `parse_args()` | 解析 `--verbose`、`--reload`、`--hf_mirror` |
| `create_app(console_log_level)` | 初始化日志、同步配置、读取 `conf.yaml`、创建 `WebSocketServer` |
| `run(console_log_level, reload)` | 读取 `system_config.host/port` 并启动 Uvicorn |

启动时会：

1. 设置 `HF_HOME`、`MODELSCOPE_CACHE` 到项目 `models/`。
2. 检查 `frontend/index.html` 是否存在。
3. 同步和备份 `conf.yaml`。
4. 构造 `WebSocketServer(config)`。
5. FastAPI startup 阶段调用 `server.initialize()`。
6. `ServiceContext.load_from_config()` 初始化 Live2D、ASR、TTS、VAD、MCP、Agent、翻译器。
7. 启动 UE 数字人 WebSocket 服务，默认监听 `0.0.0.0:10002`。

### 2.2 FastAPI 服务对象

文件：`src/open_llm_vtuber/server.py`

`WebSocketServer` 封装 FastAPI app 和静态资源挂载。

主要接口：

| 成员 | 类型/职责 |
| --- | --- |
| `app` | FastAPI 应用实例 |
| `config` | 当前完整配置 |
| `default_context_cache` | 默认服务上下文，作为新客户端会话的共享缓存来源 |
| `ue_avatar_server` | Fay/UE 数字人 WebSocket 服务 |
| `initialize()` | 加载默认上下文并启动 UE 服务 |
| `clean_cache()` | 清空并重建 `cache/` |

静态资源挂载：

| 路径 | 来源目录 | 说明 |
| --- | --- | --- |
| `/cache` | `cache/` | TTS 和临时音频输出 |
| `/live2d-models` | `live2d-models/` | Live2D 模型资源 |
| `/bg` | `backgrounds/` | 背景图 |
| `/avatars` | `avatars/` | 头像图片，仅允许常见图片扩展名 |
| `/web-tool` | `web_tool/` | 录音/调试工具 |
| `/` | `frontend/` | 打包后的前端静态文件 |

## 3. 配置接口

配置文件是 `conf.yaml`，由 `src/open_llm_vtuber/config_manager/` 内的 Pydantic 模型验证。

顶层模型：`Config`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `system_config` | `SystemConfig` | 服务端口、配置目录、工具 prompt、代理模式 |
| `character_config` | `CharacterConfig` | 角色、人设、模型、ASR/TTS/VAD/Agent 配置 |
| `live_config` | `LiveConfig` | 直播平台集成配置 |

`SystemConfig` 关键字段：

| 字段 | 说明 |
| --- | --- |
| `host` | 后端监听地址，`localhost` 会转为 `127.0.0.1` |
| `port` | 后端端口，当前项目配置为 `18080` |
| `config_alts_dir` | 角色配置候选目录 |
| `tool_prompts` | 拼入系统提示词的工具 prompt 文件映射 |
| `enable_proxy` | 是否启用 `/proxy-ws` |

`CharacterConfig` 关键字段：

| 字段 | 说明 |
| --- | --- |
| `conf_name`, `conf_uid` | 当前角色配置名称和唯一标识 |
| `live2d_model_name` | Live2D 模型名 |
| `character_name`, `human_name` | UI 和历史记录使用的显示名 |
| `persona_prompt` | 角色人设提示词 |
| `agent_config` | Agent 和 LLM 池配置 |
| `asr_config`, `tts_config`, `vad_config` | 语音识别、语音合成、语音活动检测配置 |
| `tts_preprocessor_config` | TTS 前处理和翻译配置 |

## 4. 后端 HTTP 与 WebSocket 接口

路由定义在 `src/open_llm_vtuber/routes.py`。

### 4.1 WebSocket 接口

| 路径 | 处理器 | 用途 |
| --- | --- | --- |
| `/client-ws` | `WebSocketHandler` | 主前端连接，承载聊天、音频、历史、配置、控制协议 |
| `/proxy-ws` | `ProxyHandler` | 可选代理模式，把客户端连接转发到实际 `/client-ws` |
| `/tts-ws` | 内联处理器 | 独立 TTS 流式生成接口 |

### 4.2 HTTP 接口

| 方法 | 路径 | 请求 | 返回 | 用途 |
| --- | --- | --- | --- | --- |
| `GET` | `/live2d-models/info` | 无 | `{type,count,characters}` | 扫描可用 Live2D 模型 |
| `GET` | `/api/runtime/tts-config` | 无 | 当前可编辑 TTS 配置 | 前端运行时设置 TTS |
| `PUT` | `/api/runtime/tts-config` | `{tts_model, config}` | 更新后的 TTS 配置 | 切换 TTS provider 并重建 TTS 引擎 |
| `POST` | `/api/runtime/ue-audio-cache` | `{audio}` base64 wav | `{url,path}` | 缓存浏览器收到的音频，供 UE 拉取 |
| `GET` | `/api/runtime/ue-audio-cache/{file_name}` | 文件名 | WAV 文件 | UE 获取缓存音频 |
| `POST` | `/api/runtime/ue-avatar-message` | `{message}` | `{sent,connected_clients}` | 向 UE 数字人客户端转发 Fay 兼容消息 |
| `GET` | `/api/runtime/ue-avatar-status` | 无 | `{connected_clients,clients}` | 查询 UE 数字人连接状态 |
| `POST` | `/asr` | multipart `file` | `{text}` 或 `{error}` | 上传 WAV 并转写 |

运行时 TTS 配置只允许更新 `TTS_EDITABLE_FIELDS` 白名单内字段，避免前端任意改写完整配置。

## 5. 主 WebSocket 协议

前端默认连接：`ws://127.0.0.1:18080/client-ws`。

前端连接成功后，后端发送：

| 消息类型 | 方向 | 说明 |
| --- | --- | --- |
| `full-text` | 后端 -> 前端 | 初始连接文本或字幕文本 |
| `set-model-and-conf` | 后端 -> 前端 | Live2D 模型信息、配置名、配置 UID、客户端 UID |
| `group-update` | 后端 -> 前端 | 当前群聊成员和 owner 状态 |
| `ue-avatar-status` | 后端 -> 前端 | UE 数字人连接状态 |
| `control: start-mic` | 后端 -> 前端 | 通知前端开始麦克风 |

### 5.1 前端发给后端

| `type` | 关键字段 | 后端处理 | 说明 |
| --- | --- | --- | --- |
| `text-input` | `text`, `images` | `_handle_conversation_trigger` | 文本触发单轮对话 |
| `mic-audio-data` | `audio: number[]` | `_handle_audio_data` | 麦克风 Float32 音频分片 |
| `mic-audio-end` | `images` | `_handle_conversation_trigger` | 音频输入结束，触发 ASR 和对话 |
| `raw-audio-data` | `audio` | `_handle_raw_audio_data` | VAD 模式下原始音频流 |
| `ai-speak-signal` | `idle_time`, `images` | `_handle_conversation_trigger` | 主动说话触发 |
| `interrupt-signal` | `text` | `_handle_interrupt` | 打断当前生成，`text` 是用户已听到的回复 |
| `audio-play-start` | `display_text`, `forwarded` | `_handle_audio_play_start` | 群聊中同步显示其他成员的音频文本 |
| `frontend-playback-complete` | 可选 `request_id` | `MessageHandler` | 前端播放完后唤醒后端等待点 |
| `fetch-history-list` | 无 | `_handle_history_list_request` | 获取历史列表 |
| `fetch-and-set-history` | `history_uid` | `_handle_fetch_history` | 切换当前历史 |
| `create-new-history` | 无 | `_handle_create_history` | 创建新历史 |
| `delete-history` | `history_uid` | `_handle_delete_history` | 删除历史 |
| `fetch-configs` | 无 | `_handle_fetch_configs` | 获取候选角色配置 |
| `switch-config` | `file` | `_handle_config_switch` | 切换角色配置 |
| `fetch-backgrounds` | 无 | `_handle_fetch_backgrounds` | 获取背景图列表 |
| `add-client-to-group` | `invitee_uid` | `_handle_group_operation` | 邀请客户端加入群聊 |
| `remove-client-from-group` | `target_uid` | `_handle_group_operation` | 移除成员/离开群聊 |
| `request-group-info` | 无 | `_handle_group_info` | 请求刷新群聊状态 |
| `request-init-config` | 无 | `_handle_init_config_request` | 重新请求模型和配置 |
| `heartbeat` | 无 | `_handle_heartbeat` | 心跳，返回 `heartbeat-ack` |

### 5.2 后端发给前端

| `type` | 关键字段 | 前端处理 |
| --- | --- | --- |
| `control` | `text` | 控制麦克风和对话状态 |
| `full-text` | `text` | 更新字幕 |
| `set-model-and-conf` | `model_info`, `conf_name`, `conf_uid`, `client_uid` | 设置 Live2D 模型、当前角色和客户端 UID |
| `config-files` | `configs` | 更新配置列表 |
| `config-switched` | `message` | 提示切换成功并刷新历史 |
| `background-files` | `files` | 更新背景列表 |
| `audio` | `audio`, `volumes`, `slice_length`, `display_text`, `actions`, `forwarded` | 播放音频、显示文本、驱动表情 |
| `history-data` | `messages` | 填充当前历史 |
| `new-history-created` | `history_uid` | 设置当前历史为空会话 |
| `history-deleted` | `success`, `history_uid` | UI 提示删除结果 |
| `history-list` | `histories` | 更新历史列表 |
| `user-input-transcription` | `text` | 显示 ASR 结果为用户消息 |
| `group-update` | `members`, `is_owner` | 更新群聊成员 |
| `group-operation-result` | `success`, `message` | 群聊操作提示 |
| `ue-avatar-status` | `connected_clients`, `clients` | 更新 UE 连接状态 |
| `backend-synth-complete` | 无 | 标记后端语音合成完成 |
| `force-new-message` | 无 | 前端下一段响应另起一条消息 |
| `interrupt-signal` | `text` | 被群聊转发时本地打断 |
| `tool_call_status` | `tool_id`, `tool_name`, `status`, `content`, `browser_view` | 展示工具调用状态和浏览器视图 |
| `error` | `message` | toast 错误提示 |

`control.text` 的当前取值：

| 值 | 前端行为 |
| --- | --- |
| `start-mic` | 开始录音 |
| `stop-mic` | 停止录音 |
| `interrupt` | VAD 检测到插话时触发打断 |
| `mic-audio-end` | VAD 检测到语音片段结束 |
| `conversation-chain-start` | AI 进入思考/说话状态，清空音频队列 |
| `conversation-chain-end` | 对话轮结束，按配置自动恢复麦克风 |

## 6. 后端内部接口设计

### 6.1 `WebSocketHandler`

文件：`src/open_llm_vtuber/websocket_handler.py`

职责：

1. 保存 `client_uid -> WebSocket`。
2. 为每个客户端克隆一个 `ServiceContext`。
3. 管理音频缓冲、当前对话 task、群聊状态。
4. 按消息 `type` 分发到具体 handler。
5. 在断开连接时清理群聊、task、上下文和等待事件。

关键成员：

| 成员 | 说明 |
| --- | --- |
| `client_connections` | 所有在线 WebSocket |
| `client_contexts` | 每个客户端对应的服务上下文 |
| `received_data_buffers` | 麦克风音频分片累积缓冲 |
| `current_conversation_tasks` | 单人或群聊当前对话任务 |
| `chat_group_manager` | 群聊成员和 owner 管理 |
| `_message_handlers` | `type -> handler` 路由表 |

新客户端不是重新加载全部模型，而是从 `default_context_cache` 拷贝配置并复用已初始化的 ASR/TTS/VAD/Agent 等实例引用，再初始化会话级 MCP 组件。

### 6.2 `ServiceContext`

文件：`src/open_llm_vtuber/service_context.py`

`ServiceContext` 是后端最重要的依赖容器。它把一个会话需要的配置、模型、引擎和工具组件放在一起。

主要字段：

| 字段 | 说明 |
| --- | --- |
| `config`, `system_config`, `character_config` | 验证后的配置 |
| `live2d_model` | Live2D 模型信息和表情映射 |
| `asr_engine` | 实现 `ASRInterface` 的语音识别引擎 |
| `tts_engine` | 实现 `TTSInterface` 的语音合成引擎 |
| `vad_engine` | 实现 `VADInterface` 的语音活动检测引擎 |
| `agent_engine` | 实现 `AgentInterface` 的对话 Agent |
| `translate_engine` | 可选翻译引擎 |
| `mcp_server_registery`, `tool_adapter`, `tool_manager`, `mcp_client`, `tool_executor` | MCP 工具调用链路 |
| `system_prompt` | 拼装后传给 Agent 的系统提示词 |
| `history_uid` | 当前聊天历史 ID |
| `send_text`, `client_uid` | 会话级 WebSocket 发送函数和客户端 ID |

初始化方法：

| 方法 | 说明 |
| --- | --- |
| `load_from_config(config)` | 从完整配置初始化所有组件 |
| `load_cache(...)` | 从默认上下文复制引用，为新客户端构造会话上下文 |
| `init_live2d()` | 加载 Live2D 模型元数据 |
| `init_asr()` | 通过 `ASRFactory` 创建 ASR |
| `init_tts()` | 通过 `TTSFactory` 创建 TTS |
| `init_vad()` | 通过 `VADFactory` 创建 VAD |
| `init_agent()` | 拼系统 prompt 并通过 `AgentFactory` 创建 Agent |
| `init_translate()` | 创建翻译器 |
| `handle_config_switch()` | 切换角色配置并通知前端 |

### 6.3 对话编排

入口：`src/open_llm_vtuber/conversations/conversation_handler.py`

`handle_conversation_trigger()` 根据消息类型把输入归一化：

| 输入类型 | 归一化结果 |
| --- | --- |
| `text-input` | 用户文本 |
| `mic-audio-end` | 从 `received_data_buffers[client_uid]` 取出的 numpy 音频 |
| `ai-speak-signal` | 从 `tool_prompts.proactive_speak_prompt` 加载主动发言 prompt |

然后判断当前客户端是否在多人群聊：

| 场景 | 处理函数 |
| --- | --- |
| 单人会话 | `process_single_conversation()` |
| 群聊会话 | `process_group_conversation()` |

单人会话对重复 `text-input` 采用重启策略，而不是忽略或固定延迟聚合：

1. 第一条 `text-input` 立即创建 `current_conversation_tasks[client_uid]` 并启动 `process_single_conversation()`。
2. 如果任务未完成时又收到同一 `client_uid` 的新输入，`handle_conversation_trigger()` 会取消旧任务并等待取消完成。
3. 旧任务在开始阶段已经把前序用户文本写入 agent memory；新任务把新文本作为新的 `role=user` 消息加入上下文。
4. 取消后的旧 assistant 输出不再继续发送，最终只保留重启后的一次数字人回复。

这个策略用于 UE 示例问题或文本框快速连续发送：有几条用户输入就保留几条用户消息，但不产生多次数字人回复。语音打断仍走 `interrupt-signal`，用于已播放/正在播放回复时的显式打断。

单人会话流程：

```text
send_conversation_start_signals()
  -> process_user_input()
     -> 文本直接使用
     -> 音频调用 ASRInterface.async_transcribe_np()
  -> create_batch_input()
  -> agent_engine.chat(BatchInput)
  -> process_agent_output()
     -> SentenceOutput: TTS 合成并发送 audio payload
     -> AudioOutput: 直接发送已有音频
  -> finalize_conversation_turn()
     -> 等待 TTS task
     -> 发送 backend-synth-complete
     -> 等待 frontend-playback-complete
     -> 发送 force-new-message 和 conversation-chain-end
  -> 写入 chat_history
```

### 6.4 Agent 输入输出模型

文件：

| 文件 | 说明 |
| --- | --- |
| `agent/input_types.py` | Agent 输入数据结构 |
| `agent/output_types.py` | Agent 输出数据结构 |

输入：

| 类型 | 字段 | 说明 |
| --- | --- | --- |
| `BatchInput` | `texts`, `images`, `files`, `metadata` | 一轮完整用户输入 |
| `TextData` | `source`, `content`, `from_name` | 文本输入 |
| `ImageData` | `source`, `data`, `mime_type` | 图片输入，通常是 base64 或 URL |
| `FileData` | `name`, `data`, `mime_type` | 文件输入 |

输出：

| 类型 | 字段 | 说明 |
| --- | --- | --- |
| `SentenceOutput` | `display_text`, `tts_text`, `actions` | 文本回复，需要后端 TTS |
| `AudioOutput` | `audio_path`, `display_text`, `transcript`, `actions` | Agent 自带音频 |
| `DisplayText` | `text`, `name`, `avatar` | UI 展示文本 |
| `Actions` | `expressions`, `pictures`, `sounds` | Live2D 表情、图片、音效动作 |

`metadata` 可携带特殊标记，例如主动发言使用：

| 字段 | 含义 |
| --- | --- |
| `proactive_speak` | 这是 AI 主动说话 |
| `skip_memory` | 不写 Agent 内部记忆 |
| `skip_history` | 不写本地聊天历史 |

### 6.5 TTS 输出协议

`TTSTaskManager` 负责并行生成 TTS，但按 Agent 输出顺序发送音频。它把音频文件转为 WebSocket payload：

```json
{
  "type": "audio",
  "audio": "base64 wav",
  "volumes": [0.1, 0.3, 1.0],
  "slice_length": 20,
  "display_text": {
    "text": "要显示的文本",
    "name": "角色名",
    "avatar": "头像路径"
  },
  "actions": {
    "expressions": ["happy"]
  },
  "forwarded": false
}
```

`volumes` 是按固定毫秒切片计算的归一化音量数组，前端用它驱动口型/音频可视化。

### 6.6 插件式能力接口

后端以“接口 + Factory”的方式扩展模型能力。

| 能力 | 抽象接口 | Factory | 必实现方法 |
| --- | --- | --- | --- |
| ASR | `ASRInterface` | `ASRFactory` | `transcribe_np(audio) -> str` |
| TTS | `TTSInterface` | `TTSFactory` | `generate_audio(text, file_name_no_ext) -> path` |
| VAD | `VADInterface` | `VADFactory` | `detect_speech(audio_data)` |
| Translate | `TranslateInterface` | `TranslateFactory` | `translate(text) -> str` |
| Agent | `AgentInterface` | `AgentFactory` | `chat(input_data)`, `handle_interrupt()`, `set_memory_from_history()` |
| Stateless LLM | `StatelessLLMInterface` | `LLMFactory` | `chat_completion(messages, system, tools)` |

新增一个 TTS provider 的典型步骤：

1. 在 `src/open_llm_vtuber/tts/` 新增实现类，继承 `TTSInterface`。
2. 在 `TTSFactory.get_tts_engine()` 添加 `engine_type` 分支。
3. 在 `config_manager/tts.py` 添加配置模型字段。
4. 在 `conf.yaml` 添加 provider 配置并设置 `tts_model`。
5. 如需前端运行时编辑，在 `routes.py` 的 `TTS_EDITABLE_FIELDS` 加白名单字段。

新增一个 Agent 的典型步骤：

1. 在 `src/open_llm_vtuber/agent/agents/` 新增实现类，继承 `AgentInterface`。
2. 实现 `chat()`，按流式方式 yield `SentenceOutput`、`AudioOutput` 或工具状态 dict。
3. 在 `AgentFactory.create_agent()` 添加分支。
4. 在 `config_manager/agent.py` 和 `conf.yaml` 增加配置。

### 6.7 VAD/ASR/TTS/LLM 等统一接入规范

本项目对“可替换能力”采用同一套接入范式：

```text
配置选择字段
  -> Pydantic 配置模型
  -> ServiceContext.init_xxx()
  -> XxxFactory.get_xxx()
  -> 统一抽象接口
  -> 对话流程只依赖抽象接口
```

这套模式的目标是：对话编排层不关心底层是本地模型、云 API、Web 服务还是命令行封装，只调用统一方法。

#### 6.7.1 统一接入的四个固定位置

新增任何一种 VAD、ASR、TTS、LLM、Agent 或翻译器，通常都要改这四处：

| 位置 | 责任 | 示例 |
| --- | --- | --- |
| 抽象接口 | 定义运行时统一调用方法 | `asr/asr_interface.py`, `tts/tts_interface.py` |
| 实现类 | 封装具体 provider 的 SDK/API/本地模型 | `tts/edge_tts.py`, `asr/sherpa_onnx_asr.py` |
| Factory | 根据配置名实例化实现类 | `TTSFactory.get_tts_engine()` |
| 配置模型 | 让 `conf.yaml` 可被验证和补全 | `config_manager/tts.py` |

如果这个 provider 需要在前端运行时编辑，还要额外改：

| 位置 | 责任 |
| --- | --- |
| `routes.py` 的 `TTS_EDITABLE_FIELDS` | 白名单允许前端修改的字段 |
| 前端设置 UI | 显示和提交这些字段 |

#### 6.7.2 配置选择字段的统一约定

每类能力都有一个“选择字段”和一组“同名配置块”。选择字段决定当前使用哪个 provider。

| 能力 | 选择字段 | 配置块字段 | 例子 |
| --- | --- | --- | --- |
| ASR | `character_config.asr_config.asr_model` | `asr_config.{provider}` | `asr_model: sherpa_onnx_asr` + `sherpa_onnx_asr: {...}` |
| TTS | `character_config.tts_config.tts_model` | `tts_config.{provider}` | `tts_model: edge_tts` + `edge_tts: {...}` |
| VAD | `character_config.vad_config.vad_model` | `vad_config.{provider}` | `vad_model: silero_vad` + `silero_vad: {...}` |
| Agent | `character_config.agent_config.conversation_agent_choice` | `agent_settings.{agent}` | `conversation_agent_choice: basic_memory_agent` |
| LLM | `basic_memory_agent.llm_provider` | `llm_configs.{provider}` | `llm_provider: deepseek_llm` |
| Translate | `tts_preprocessor_config.translator_config.translate_provider` | provider-specific config | `translate_provider: deeplx` |

运行时初始化时，`ServiceContext` 会按这个选择字段取出对应配置块：

```python
self.asr_engine = ASRFactory.get_asr_system(
    asr_config.asr_model,
    **getattr(asr_config, asr_config.asr_model).model_dump(),
)
```

TTS 也是相同思想：

```python
self.tts_engine = TTSFactory.get_tts_engine(
    tts_config.tts_model,
    **getattr(tts_config, tts_config.tts_model.lower()).model_dump(),
)
```

因此，provider 名称要尽量保持一致：配置选择值、配置块字段、Factory 分支、实现文件命名最好一一对应。

#### 6.7.3 ASR 统一接入

ASR 的统一接口是 `ASRInterface`：

```python
class ASRInterface:
    async def async_transcribe_np(self, audio: np.ndarray) -> str
    def transcribe_np(self, audio: np.ndarray) -> str
```

对话流程只会把 `np.ndarray` 音频交给 `async_transcribe_np()`，得到文本。默认异步方法会用 `asyncio.to_thread()` 包装同步 `transcribe_np()`，所以普通 provider 只实现同步方法即可。

当前 ASR provider：

| `asr_model` | 实现文件 | 配置模型 |
| --- | --- | --- |
| `faster_whisper` | `asr/faster_whisper_asr.py` | `FasterWhisperConfig` |
| `whisper_cpp` | `asr/whisper_cpp_asr.py` | `WhisperCPPConfig` |
| `whisper` | `asr/openai_whisper_asr.py` | `WhisperConfig` |
| `azure_asr` | `asr/azure_asr.py` | `AzureASRConfig` |
| `fun_asr` | `asr/fun_asr.py` | `FunASRConfig` |
| `groq_whisper_asr` | `asr/groq_whisper_asr.py` | `GroqWhisperASRConfig` |
| `sherpa_onnx_asr` | `asr/sherpa_onnx_asr.py` | `SherpaOnnxASRConfig` |

新增 ASR provider 的步骤：

1. 新增 `src/open_llm_vtuber/asr/my_asr.py`。
2. 定义实现类，继承 `ASRInterface`，实现 `transcribe_np(audio) -> str`。
3. 在 `config_manager/asr.py` 新增 `MyASRConfig`。
4. 把 provider 名加入 `ASRConfig.asr_model` 的 `Literal[...]`。
5. 在 `ASRConfig` 增加字段：`my_asr: Optional[MyASRConfig] = Field(None, alias="my_asr")`。
6. 在 `ASRFactory.get_asr_system()` 添加 `elif system_name == "my_asr"` 分支。
7. 在 `conf.yaml` 的 `character_config.asr_config` 下添加：

```yaml
asr_config:
  asr_model: my_asr
  my_asr:
    api_url: http://127.0.0.1:9000
    language: zh
```

接入注意点：

| 点 | 要求 |
| --- | --- |
| 输入格式 | 后端传入的是 float32 `np.ndarray`，通常采样率按 `ASRInterface.SAMPLE_RATE = 16000` 处理 |
| 返回值 | 必须返回纯文本字符串，不要返回 provider 原始 JSON |
| 耗时实现 | 同步阻塞实现可以只写 `transcribe_np()`；真异步 SDK 可以重写 `async_transcribe_np()` |
| 错误处理 | provider 内部可以抛异常，上层会通过 WebSocket `error` 返回前端 |

#### 6.7.4 TTS 统一接入

TTS 的统一接口是 `TTSInterface`：

```python
class TTSInterface:
    async def async_generate_audio(self, text: str, file_name_no_ext=None) -> str
    def generate_audio(self, text: str, file_name_no_ext=None) -> str
    def remove_file(self, filepath: str, verbose: bool = True) -> None
    def generate_cache_file_name(self, file_name_no_ext=None, file_extension="wav")
```

对话流程只关心：给一段文本，返回一个音频文件路径。后续由 `prepare_audio_payload()` 读取音频，转成 base64 WAV 和音量数组，再发给前端。

当前 TTS provider：

| `tts_model` | 实现文件 | 配置模型 |
| --- | --- | --- |
| `azure_tts` | `tts/azure_tts.py` | `AzureTTSConfig` |
| `bark_tts` | `tts/bark_tts.py` | `BarkTTSConfig` |
| `edge_tts` | `tts/edge_tts.py` | `EdgeTTSConfig` |
| `cosyvoice_tts` | `tts/cosyvoice_tts.py` | `CosyvoiceTTSConfig` |
| `cosyvoice2_tts` | `tts/cosyvoice2_tts.py` | `Cosyvoice2TTSConfig` |
| `melo_tts` | `tts/melo_tts.py` | `MeloTTSConfig` |
| `coqui_tts` | `tts/coqui_tts.py` | `CoquiTTSConfig` |
| `x_tts` | `tts/x_tts.py` | `XTTSConfig` |
| `gpt_sovits_tts` | `tts/gpt_sovits_tts.py` | `GPTSoVITSConfig` |
| `fish_api_tts` | `tts/fish_api_tts.py` | `FishAPITTSConfig` |
| `sherpa_onnx_tts` | `tts/sherpa_onnx_tts.py` | `SherpaOnnxTTSConfig` |
| `siliconflow_tts` | `tts/siliconflow_tts.py` | `SiliconFlowTTSConfig` |
| `openai_tts` | `tts/openai_tts.py` | `OpenAITTSConfig` |
| `spark_tts` | `tts/spark_tts.py` | `SparkTTSConfig` |
| `minimax_tts` | `tts/minimax_tts.py` | `MinimaxTTSConfig` |
| `elevenlabs_tts` | `tts/elevenlabs_tts.py` | `ElevenLabsTTSConfig` |
| `cartesia_tts` | `tts/cartesia_tts.py` | `CartesiaTTSConfig` |
| `piper_tts` | `tts/piper_tts.py` | `PiperTTSConfig` |

新增 TTS provider 的步骤：

1. 新增 `src/open_llm_vtuber/tts/my_tts.py`。
2. 定义实现类，继承 `TTSInterface`，实现 `generate_audio(text, file_name_no_ext) -> str`。
3. 使用 `self.generate_cache_file_name(file_name_no_ext, file_extension)` 生成输出路径，或者返回 provider 生成的本地音频路径。
4. 在 `config_manager/tts.py` 新增 `MyTTSConfig`。
5. 把 provider 名加入 `TTSConfig.tts_model` 的 `Literal[...]`。
6. 在 `TTSConfig` 增加字段：`my_tts: Optional[MyTTSConfig] = Field(None, alias="my_tts")`。
7. 在 `TTSFactory.get_tts_engine()` 添加 `elif engine_type == "my_tts"` 分支。
8. 在 `conf.yaml` 的 `character_config.tts_config` 下添加配置。
9. 如需前端运行时切换/编辑，在 `routes.py` 的 `TTS_EDITABLE_FIELDS` 添加可编辑字段。

最小实现形状：

```python
from .tts_interface import TTSInterface


class TTSEngine(TTSInterface):
    def __init__(self, api_url: str, voice: str):
        self.api_url = api_url
        self.voice = voice

    def generate_audio(self, text: str, file_name_no_ext=None) -> str:
        output_path = self.generate_cache_file_name(file_name_no_ext, "wav")
        # 调用 SDK/API，把音频写入 output_path
        return output_path
```

接入注意点：

| 点 | 要求 |
| --- | --- |
| 输出路径 | 必须返回后端本机可读的音频文件路径 |
| 音频格式 | `prepare_audio_payload()` 会用 pydub 读取并导出 WAV；provider 输出 mp3/wav 通常都可行，但要确保 pydub/ffmpeg 能解码 |
| 清理 | `TTSTaskManager` 在发送后调用 `tts_engine.remove_file(audio_file_path)` |
| 流式 TTS | 当前统一接口以“每句返回音频文件”为核心；真流式 provider 需要在实现内部聚合为文件，或扩展 `AudioOutput`/对话流程 |
| 静音文本 | 空白 TTS 文本不会调用 provider，会发 silent audio payload 只显示文本/动作 |

#### 6.7.5 VAD 统一接入

VAD 的统一接口是 `VADInterface`：

```python
class VADInterface:
    def detect_speech(self, audio_data: bytes)
```

VAD 用在 `WebSocketHandler._handle_raw_audio_data()`。前端发送 `raw-audio-data` 后，后端调用 `context.vad_engine.detect_speech(chunk)`，根据返回内容决定：

| VAD 返回 | 后端行为 |
| --- | --- |
| `b"<|PAUSE|>"` | 给前端发 `control: interrupt` |
| `b"<|RESUME|>"` | 当前忽略 |
| 长度大于 1024 的音频 bytes | 追加到 `received_data_buffers`，并发 `control: mic-audio-end` 触发对话 |

当前 VAD provider：

| `vad_model` | 实现文件 | 配置模型 |
| --- | --- | --- |
| `None` | 无 | 关闭 VAD |
| `silero_vad` | `vad/silero.py` | `SileroVADConfig` |

新增 VAD provider 的步骤：

1. 新增 `src/open_llm_vtuber/vad/my_vad.py`。
2. 继承 `VADInterface`，实现 `detect_speech(audio_data)`。
3. 在 `config_manager/vad.py` 新增配置模型。
4. 把 provider 名加入 `VADConfig.vad_model` 的 `Literal[...]`。
5. 增加配置字段：`my_vad: Optional[MyVADConfig] = Field(None, alias="my_vad")`。
6. 在 `VADFactory.get_vad_engine()` 添加分支。
7. 在 `conf.yaml` 添加：

```yaml
vad_config:
  vad_model: my_vad
  my_vad:
    threshold: 0.5
```

接入注意点：

| 点 | 要求 |
| --- | --- |
| 返回协议 | 必须兼容 `_handle_raw_audio_data()` 当前识别的三类返回 |
| 音频格式 | 当前 handler 把返回的语音 bytes 按 `np.int16` 转 float32，provider 应返回 16-bit PCM bytes |
| 关闭方式 | `vad_model: null` 表示关闭 VAD，`ServiceContext.init_vad()` 会把 `vad_engine` 设为 `None` |

#### 6.7.6 LLM 与 Agent 的统一接入

LLM 与 Agent 是两层：

| 层 | 抽象 | 责任 |
| --- | --- | --- |
| Stateless LLM | `StatelessLLMInterface` | 无状态 chat completion，不保存记忆 |
| Agent | `AgentInterface` | 维护上下文/记忆/工具/输出切句，并向上游流式产出 `SentenceOutput` 或 `AudioOutput` |

`basic_memory_agent` 的创建链路：

```text
agent_config.conversation_agent_choice = basic_memory_agent
  -> agent_settings.basic_memory_agent.llm_provider
  -> llm_configs.{llm_provider}
  -> LLMFactory.create_llm()
  -> BasicMemoryAgent(llm=..., system=..., tool_manager=..., tool_executor=...)
```

当前 LLM provider：

| `llm_provider` | 实现 |
| --- | --- |
| `openai_compatible_llm`, `openai_llm`, `gemini_llm`, `zhipu_llm`, `deepseek_llm`, `groq_llm`, `mistral_llm`, `lmstudio_llm` | `openai_compatible_llm.AsyncLLM` |
| `stateless_llm_with_template` | `stateless_llm_with_template.AsyncLLMWithTemplate` |
| `ollama_llm` | `ollama_llm.OllamaLLM` |
| `llama_cpp_llm` | `llama_cpp_llm.LLM` |
| `claude_llm` | `claude_llm.AsyncLLM` |

当前 Agent provider：

| `conversation_agent_choice` | 实现 |
| --- | --- |
| `basic_memory_agent` | `agents/basic_memory_agent.py` |
| `mem0_agent` | `agents/mem0_llm.py` |
| `hume_ai_agent` | `agents/hume_ai.py` |
| `letta_agent` | `agents/letta_agent.py` |

新增 OpenAI-compatible LLM 最简单：通常不需要写代码，只在 `conf.yaml` 里新增或复用某个 `llm_configs` provider，设置 `base_url`、`llm_api_key`、`model`，并让 `basic_memory_agent.llm_provider` 指向它。

新增非兼容 LLM 的步骤：

1. 新增 `agent/stateless_llm/my_llm.py`，继承 `StatelessLLMInterface`。
2. 实现 `chat_completion(messages, system, tools)`，按异步迭代器 yield 文本块。
3. 在 `config_manager/stateless_llm.py` 新增配置模型和 `StatelessLLMConfigs` 字段。
4. 在 `BasicMemoryAgentConfig.llm_provider` 的 `Literal[...]` 加 provider 名。
5. 在 `LLMFactory.create_llm()` 添加分支。

新增 Agent 的步骤与 6.6 相同，但要注意输出协议：`chat()` 不应直接操作 WebSocket，而是 yield 标准输出对象，交给 `conversation_utils.process_agent_output()` 处理。

#### 6.7.7 翻译器统一接入

翻译器在 TTS 前处理阶段使用。统一接口是：

```python
class TranslateInterface:
    def translate(self, text: str) -> str
```

当前 provider：

| provider | 实现文件 |
| --- | --- |
| `deeplx` | `translate/deeplx.py` |
| `tencent` | `translate/tencent.py` |

接入链路：

```text
tts_preprocessor_config.translator_config.translate_audio = true
  -> translate_provider
  -> TranslateFactory.get_translator()
  -> handle_sentence_output() 中先 translate(tts_text)，再 TTS
```

新增翻译器：

1. 新增 `translate/my_translate.py`，继承 `TranslateInterface`。
2. 在 `TranslateFactory.get_translator()` 添加分支。
3. 在对应 config model 中补充 provider 配置字段。
4. 在 `conf.yaml` 的 translator 配置里启用。

#### 6.7.8 接入前的自检清单

接入任意 provider 后，至少检查这些点：

| 检查项 | 为什么 |
| --- | --- |
| `conf.yaml` 能通过 `validate_config()` | 防止启动时配置解析失败 |
| Factory 分支名与配置选择值一致 | 否则 `Unknown ...` |
| 实现类构造参数与 Factory 传参一致 | 否则启动初始化失败 |
| 抽象接口返回值符合对话流程预期 | 否则运行时 WebSocket 出错 |
| TTS 输出文件能被 pydub 读取 | 否则无法构造前端音频 payload |
| ASR 输入音频格式匹配 provider 要求 | 否则识别为空或报错 |
| VAD 返回协议符合 `_handle_raw_audio_data()` | 否则无法自动触发打断/收音结束 |

最小验证命令：

```bash
uv run run_server.py --verbose
```

启动成功后，用前端 `http://127.0.0.1:3000/` 发送文本或语音，观察后端是否完成：

```text
Initializing ASR/TTS/VAD/Agent
Conversation Chain started
User input
audio payload sent
backend-synth-complete
conversation-chain-end
```

### 6.8 MCP 工具接口

MCP 链路位于 `src/open_llm_vtuber/mcpp/`。

主要角色：

| 组件 | 责任 |
| --- | --- |
| `ServerRegistry` | 读取/登记 MCP server |
| `ToolAdapter` | 获取 server/tool 信息，生成 LLM 可用工具 schema 和 prompt |
| `ToolManager` | 保存 OpenAI/Claude 格式工具定义和原始工具信息 |
| `MCPClient` | 会话级 MCP client，负责实际通信 |
| `ToolExecutor` | 根据 tool call 执行 MCP 工具 |

`ServiceContext._init_mcp_components()` 根据 `basic_memory_agent.use_mcpp` 和 `mcp_enabled_servers` 决定是否初始化这些组件，并把 `tool_manager`、`tool_executor`、`mcp_prompt_string` 注入 Agent。

## 7. 前端接口设计

### 7.1 前端分层

| 层 | 目录/文件 | 责任 |
| --- | --- | --- |
| 连接层 | `services/websocket-service.tsx` | 创建 WebSocket、发送 JSON、用 RxJS Subject 广播消息和连接状态 |
| 协议适配层 | `services/websocket-handler.tsx` | 订阅消息，根据 `type` 更新 Context、音频队列和 UI |
| 状态层 | `context/*.tsx` | AI 状态、Live2D 配置、聊天历史、背景、群聊、VAD、渲染模式等 |
| 业务 hooks | `hooks/**` | 用户输入、音频发送、打断、主动说话、历史、群聊等 |
| UI 组件 | `components/**` | 控制台、Live2D 画布、侧栏、底部输入、设置 |

`App.tsx` 通过 Provider 组合全局状态：

```text
ModeProvider
  -> CameraProvider
  -> ScreenCaptureProvider
  -> CharacterConfigProvider
  -> ChatHistoryProvider
  -> AiStateProvider
  -> ProactiveSpeakProvider
  -> Live2DConfigProvider
  -> SubtitleProvider
  -> AvatarRendererProvider
  -> VADProvider
  -> BgUrlProvider
  -> GroupProvider
  -> BrowserProvider
  -> WebSocketHandler
  -> AppContent
```

### 7.2 WebSocket 连接层

文件：`frontend/src/renderer/src/services/websocket-service.tsx`

`WebSocketService` 是单例。

主要接口：

| 方法 | 说明 |
| --- | --- |
| `connect(url)` | 连接后端 WebSocket；若已有连接会先断开 |
| `sendMessage(message)` | JSON.stringify 后发送 |
| `onMessage(callback)` | 订阅服务端消息 |
| `onStateChange(callback)` | 订阅连接状态 |
| `disconnect()` | 关闭连接 |
| `getCurrentState()` | 返回当前连接状态 |

连接打开后会自动发送初始化请求：

```text
fetch-backgrounds
fetch-configs
fetch-history-list
create-new-history
```

默认 URL 定义在 `context/websocket-context.tsx`：

| 常量 | 值 |
| --- | --- |
| `defaultWsUrl` | `ws://127.0.0.1:18080/client-ws` |
| `defaultBaseUrl` | `http://127.0.0.1:18080` |

### 7.3 前端发消息的主要 hooks

| hook | 文件 | 发送消息 |
| --- | --- | --- |
| `useTextInput()` | `hooks/footer/use-text-input.tsx` | `text-input` |
| `useSendAudio()` | `hooks/utils/use-send-audio.tsx` | 多个 `mic-audio-data` + 一个 `mic-audio-end` |
| `useInterrupt()` | `hooks/utils/use-interrupt.ts` | `interrupt-signal` |
| `useTriggerSpeak()` | `hooks/utils/use-trigger-speak.ts` | `ai-speak-signal` |
| `useGroupDrawer()` | `hooks/sidebar/use-group-drawer.tsx` | `request-group-info`, `add-client-to-group`, `remove-client-from-group` |
| `useHistoryDrawer()` | `hooks/sidebar/use-history-drawer.ts` | `fetch-and-set-history`, `delete-history` |

### 7.4 消息接收分发

文件：`frontend/src/renderer/src/services/websocket-handler.tsx`

`handleWebSocketMessage()` 是前端服务端协议总入口。它按 `message.type` 更新不同 Context：

| 消息类型 | 主要副作用 |
| --- | --- |
| `set-model-and-conf` | 更新角色配置、客户端 UID、Live2D 模型 URL |
| `audio` | 根据渲染模式分流到 Live2D、LiveTalking 或 UE5 |
| `control` | 更新麦克风和 AI 状态 |
| `history-*` | 更新聊天历史上下文 |
| `group-*` | 更新群聊上下文 |
| `tool_call_status` | 更新工具调用消息和浏览器视图 |
| `ue-avatar-status` | 更新 UE 数字人连接状态 |

音频分流规则：

| `avatarMode` | 行为 |
| --- | --- |
| `live2d` | 调用 `addAudioTask()`，前端播放 base64 音频并驱动 Live2D |
| `livetalking` | 调用 `consumeLiveTalkingAudio()`，把音频传给 LiveTalking 服务 |
| `ue5` | 调用 `consumeUeAudio()`，缓存音频并通过后端转发给 UE 客户端 |

## 8. 渲染器接口：Live2D、LiveTalking、UE5

前端统一由 `AvatarRendererProvider` 管理渲染模式。

文件：`frontend/src/renderer/src/context/avatar-renderer-context.tsx`

主要接口：

| 方法 | 说明 |
| --- | --- |
| `setMode(mode)` | 切换 `live2d`、`livetalking`、`ue5` |
| `connectLiveTalking()` | 建立 LiveTalking WebRTC 连接 |
| `consumeLiveTalkingAudio(message)` | 把回复音频发送到 LiveTalking `/humanaudio` |
| `consumeUeAudio(message, baseUrl)` | 把回复音频发送给 UE 数字人桥接 |
| `sendUeQuestion(text, baseUrl)` | 发送用户问题到 UE |
| `sendUeLog(text, baseUrl)` | 发送状态日志到 UE |
| `sendUeText(text, baseUrl, options)` | 发送文本流到 UE |
| `finishUeAudio()` | 发送 UE 音频结束帧 |
| `interruptActiveRenderer()` | 打断当前外部渲染器 |

### 8.1 LiveTalking

文件：`frontend/src/renderer/src/services/livetalking-client.ts`

对外部 LiveTalking 服务的接口：

| 方法 | 外部接口 | 说明 |
| --- | --- | --- |
| `connect(onTrack)` | `POST {serviceUrl}/offer` | 建 WebRTC offer/answer，接收远程视频/音频流 |
| `sendAudio(audioBase64)` | `POST {serviceUrl}/humanaudio` | 发送回复 WAV 音频 |
| `interrupt()` | `POST {serviceUrl}/interrupt_talk` | 打断说话 |
| `disconnect()` | 本地关闭 RTCPeerConnection | 释放连接 |

### 8.2 UE5/Fay 兼容数字人

后端文件：

| 文件 | 责任 |
| --- | --- |
| `ue_avatar_server.py` | 独立 WebSocket server，默认 `0.0.0.0:10002`，接收 UE 客户端连接 |
| `ue_avatar_protocol.py` | 把问题、日志、文本、音频转换为 Fay 兼容消息 |

前端文件：`frontend/src/renderer/src/services/ue-avatar-client.ts`

前端不直接连 UE WebSocket，而是调用后端 HTTP：

| 前端方法 | 后端接口 | 说明 |
| --- | --- | --- |
| `cacheAudio()` | `POST /api/runtime/ue-audio-cache` | 把 base64 音频缓存成 URL |
| `sendUeAvatarMessage()` | `POST /api/runtime/ue-avatar-message` | 让后端转发 Fay 消息 |
| `sendAudio()` | 上面两个接口组合 | 发送音频帧，带 `CONV_ID` 和序号 |
| `sendEnd()` | `/api/runtime/ue-avatar-message` | 发送 `IsEnd=1` |

## 9. Electron IPC 接口

Electron 主进程：`frontend/src/main/index.ts`

Preload 暴露：`frontend/src/preload/index.ts`

`window.api` 提供给 React 的主要接口：

| 接口 | IPC 通道 | 用途 |
| --- | --- | --- |
| `setIgnoreMouseEvents(ignore)` | `set-ignore-mouse-events` | 桌宠模式鼠标穿透 |
| `toggleForceIgnoreMouse()` | `toggle-force-ignore-mouse` | 强制切换鼠标穿透 |
| `onForceIgnoreMouseChanged(cb)` | `force-ignore-mouse-changed` | 监听穿透状态 |
| `onModeChanged(cb)` | `mode-changed` | 监听窗口/桌宠模式切换 |
| `onMicToggle(cb)` | `mic-toggle` | 托盘或快捷入口切换麦克风 |
| `onInterrupt(cb)` | `interrupt` | 系统入口触发打断 |
| `updateComponentHover(id, hovering)` | `update-component-hover` | 桌宠模式判断哪些 UI 可点击 |
| `onSwitchCharacter(cb)` | `switch-character` | 托盘菜单切换角色 |
| `setMode(mode)` | `pre-mode-changed` | 请求主进程切换窗口形态 |
| `getConfigFiles()` | `get-config-files` | 读取配置列表 |
| `updateConfigFiles(files)` | `update-config-files` | 同步配置列表到托盘 |

`WindowManager` 负责把窗口在两种模式间切换：

| 模式 | 行为 |
| --- | --- |
| `window` | 常规应用窗口，可调整大小，可聚焦 |
| `pet` | 透明、置顶、跨屏全屏覆盖，可根据 hover 控制鼠标穿透 |

## 10. 持久化与文件接口

| 数据 | 位置 | 管理代码 |
| --- | --- | --- |
| 主配置 | `conf.yaml` | `config_manager`, `routes.py` |
| 角色候选配置 | `characters/` 或 `system_config.config_alts_dir` | `scan_config_alts_directory()` |
| 聊天历史 | `chat_history/{conf_uid}/{history_uid}.json` | `chat_history_manager.py` |
| 临时音频 | `cache/` | `TTSInterface.generate_cache_file_name()`, `stream_audio.py` |
| UE 音频缓存 | `cache/ue_audio/*.wav` | `routes.py`, `ue_avatar_protocol.py` |
| Live2D 模型 | `live2d-models/` | `Live2dModel`, `/live2d-models/info` |
| 背景图 | `backgrounds/` | `/bg`, `fetch-backgrounds` |
| 头像 | `avatars/` | `/avatars` |

聊天历史文件包含一个 `metadata` 项和若干消息项。普通消息字段：

| 字段 | 说明 |
| --- | --- |
| `role` | `human` 或 `ai` |
| `timestamp` | ISO 时间 |
| `content` | 消息文本 |
| `name` | 可选显示名 |
| `avatar` | 可选头像 |

## 11. 常见二次开发入口

### 11.1 新增一个 WebSocket 消息

后端：

1. 在 `WebSocketHandler._init_message_handlers()` 加 `type -> handler`。
2. 新增 `_handle_xxx()`，读取 `data` 并返回 `websocket.send_text/json`。
3. 如需前端响应，在 `websocket-service.tsx` 的 `MessageEvent` 增加字段。
4. 在 `websocket-handler.tsx` 的 `switch(message.type)` 添加 case。

### 11.2 新增一个 HTTP API

1. 在 `routes.py` 的 `init_webtool_routes()` 或独立 router 中添加路径。
2. 用 Pydantic `BaseModel` 定义请求体。
3. 需要使用模型/配置时，通过传入的 `default_context_cache` 访问当前默认引擎。
4. 如果返回静态文件，注意路径校验和文件类型限制。

### 11.3 新增一个模型 provider

按第 6.6 节的接口和 Factory 分支添加。项目的核心扩展策略是：业务编排层只依赖接口，provider 细节留在实现类和 Factory。

### 11.4 调整对话流程

优先看这些文件：

| 文件 | 修改场景 |
| --- | --- |
| `conversation_handler.py` | 新增触发类型、单人/群聊路由规则 |
| `single_conversation.py` | 单人一轮对话主流程 |
| `group_conversation.py` | 多客户端群聊流程 |
| `conversation_utils.py` | 输入处理、Agent 输出处理、开始/结束信号 |
| `tts_manager.py` | TTS 并发、排序、音频 payload 发送 |

### 11.5 调整前端播放或渲染

优先看这些文件：

| 文件 | 修改场景 |
| --- | --- |
| `services/websocket-handler.tsx` | 后端消息如何影响 UI |
| `context/avatar-renderer-context.tsx` | Live2D/LiveTalking/UE5 模式切换 |
| `components/canvas/live2d.tsx` | Live2D 播放、口型、表情 |
| `utils/audio-manager.ts`, `utils/task-queue.ts` | 音频播放队列 |
| `hooks/utils/use-audio-task.ts` | 音频任务执行与打断 |

## 12. 阅读代码建议顺序

如果你想快速建立全局理解，建议按这个顺序读：

1. `run_server.py`
2. `src/open_llm_vtuber/server.py`
3. `src/open_llm_vtuber/routes.py`
4. `src/open_llm_vtuber/websocket_handler.py`
5. `src/open_llm_vtuber/service_context.py`
6. `src/open_llm_vtuber/conversations/conversation_handler.py`
7. `src/open_llm_vtuber/conversations/single_conversation.py`
8. `src/open_llm_vtuber/agent/input_types.py`
9. `src/open_llm_vtuber/agent/output_types.py`
10. `frontend/src/renderer/src/services/websocket-service.tsx`
11. `frontend/src/renderer/src/services/websocket-handler.tsx`
12. `frontend/src/renderer/src/App.tsx`
13. `frontend/src/renderer/src/context/*.tsx`

这条路径基本覆盖“启动、连接、输入、推理、合成、播放、状态更新”的完整闭环。
