# Open-LLM-VTuber UE Integration Notes

当前目录：`D:\AI\Open-LLM-VTuber`

## 本轮已完成事项

- 将主前端运行时页面改成数字人控制台形态，保留 Live2D、LiveTalking、UE5 三种数字人模式。
- LiveTalking 已接入现有服务，默认服务地址为 `http://localhost:8010`。
- Live2D 可在控制台中切换模型，之前已修复 shizuku 保存不生效的问题。
- 隐藏了左下角群组入口。
- 增加了运行时 TTS 设置入口，可切换 TTS provider 并保存部分安全字段。
- 后端和前端均按热更新模式运行。

## UE 数字人协议

UE 集成最终按 Fay 的协议方向实现：

- Open-LLM-VTuber 后端监听 `10002`。
- UE/UEPIE 作为 WebSocket 客户端连接 `ws://127.0.0.1:10002`。
- UE 连接后发送：

```json
{"Username":"User","Output":true}
```

后端会向 UE 推送 Fay 兼容消息：

- `Data.Key=question`：用户问题。
- `Data.Key=log`：思考中、清空状态等。
- `Data.Key=text`：分段字幕。
- `Data.Key=audio`：音频播放消息。
- `Data.Key=suggestions`：推荐提问/追问选项，只用于 UI 按钮，不进入 TTS。

音频消息同时包含：

- `Data.HttpValue`：HTTP WAV URL，例如 `http://127.0.0.1:18080/api/runtime/ue-audio-cache/xxx.wav`。
- `Data.Value`：Windows 本地路径，例如 `D:\AI\Open-LLM-VTuber\cache\ue_audio\xxx.wav`。

实际验证中，UE 蓝图对音频播放依赖 Fay 风格的 `Value` 本地路径，所以不要移除它。

推荐提问消息格式：

```json
{
  "Topic": "human",
  "Data": {
    "Key": "suggestions",
    "Value": [
      "今日用电负荷如何？",
      "电网运行是否稳定？",
      "重点工程进展情况？"
    ],
    "Context": "initial"
  },
  "Username": "User"
}
```

`Context=initial` 表示初始示例问题，`Context=follow_up` 表示一轮回答后的追问。后端在 `process_single_conversation()` 完整拿到 `input_text` 与 `full_response` 后生成追问并推给 UE；初始示例可通过 `POST /api/runtime/ue-suggestions` 主动生成并派发。

## Pixel Streaming

UE5 Pixel Streaming 默认地址已设置为：

```text
http://127.0.0.1:80
```

这个地址只负责把 UE 画面嵌到前端 iframe。UE 的文本/音频协议不依赖 Pixel Streaming 地址，仍走后端 `10002`。

## 关键文件

后端：

- `src/open_llm_vtuber/ue_avatar_server.py`：Fay 兼容 UE WebSocket 服务，监听 `10002`。
- `src/open_llm_vtuber/ue_avatar_protocol.py`：发送 `question/log/text/audio/suggestions`，缓存音频并生成 `Value`/`HttpValue`。
- `src/open_llm_vtuber/routes.py`：运行时 TTS 配置、UE 音频缓存、UE 状态接口；`POST /api/runtime/ue-suggestions` 生成初始示例问题并可派发给 UE。
- `src/open_llm_vtuber/server.py`：启动 UE WebSocket 服务。
- `run_server.py`：关闭时停止 UE WebSocket 服务。
- `src/open_llm_vtuber/conversations/conversation_utils.py`：在对话开始、用户输入、对话结束时推 UE 消息。
- `src/open_llm_vtuber/conversations/tts_manager.py`：在 TTS payload 按序发送时推 UE `text/audio`。

前端子模块：

- `frontend/src/renderer/src/types/avatar-renderer.ts`：数字人模式默认配置，UE Pixel Streaming 默认值。
- `frontend/src/renderer/src/context/avatar-renderer-context.tsx`：数字人运行时状态。
- `frontend/src/renderer/src/services/websocket-handler.tsx`：UE5 模式下前端不再播放 AI 音频。
- `frontend/src/renderer/src/services/ue-avatar-client.ts`：保留前端 UE client facade，但协议发送已后端化。
- `frontend/src/renderer/src/components/console/digital-human-stage.tsx`：数字人舞台。
- `frontend/src/renderer/src/components/console/digital-human-settings.tsx`：数字人/TTS 设置。

## 前端仓库说明

`frontend` 是 Git 子模块/独立 Git 仓库，不是普通编译产物目录。

`frontend/.git` 是一个文本指针文件：

```text
gitdir: ../.git/modules/frontend
```

真实 Git 数据在：

```text
.git/modules/frontend
```

当前前端子模块提交：

```text
ca337f5 Default UE Pixel Streaming to localhost port 80
```

当前根仓库相关提交：

```text
e9c6b33 Point frontend at default UE Pixel Streaming URL
14e6041 Serve UE avatars with Fay-compatible backend protocol
```

## 运行与诊断

当前常用服务：

- 前端 Vite：`http://127.0.0.1:3000`
- 后端 FastAPI：`http://127.0.0.1:18080`
- UE WebSocket：`ws://127.0.0.1:10002`
- LiveTalking：`http://127.0.0.1:8010`

检查 UE 是否连接：

```bash
curl http://127.0.0.1:18080/api/runtime/ue-avatar-status
```

前端运行时不轮询该接口；后端会通过现有 `/client-ws` 主动推送：

```json
{"type":"ue-avatar-status","connected_clients":1,"clients":[{"username":"User","output":true,"remote_address":"127.0.0.1:47427"}]}
```

正常返回示例：

```json
{"connected_clients":1,"clients":[{"username":"User","output":true,"remote_address":"127.0.0.1:47427"}]}
```

后端热更新会断开 UEPIE 的 `10002` 连接。热更新后需要让 UEPIE 重新连接。

## 验证记录

已运行过：

- `npm run typecheck:web`
- `npm run build:web`
- `uv run python -m py_compile ...`
- `git diff --check` 针对触碰文件
- 手动 UEPIE 验证：文本和音频均已收到

## 注意事项

- 根仓库存在大量既有无关脏文件，多数是行尾或历史变动。不要随意 revert。
- `frontend/index.html` 曾出现未跟踪文件，不属于本轮 UE 功能提交。
- 继续改 UE 协议时优先保持 Fay 兼容字段，不要只保留 `HttpValue`。
- 若 UE 收不到音频，先查：
  - `/api/runtime/ue-avatar-status`
  - 后端日志中的 `UE avatar message dispatched`
  - `Data.Value` 是否是 Windows 路径
  - `Data.HttpValue` 是否能从 Windows 下载
