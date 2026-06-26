# 数字人控制协议与扩展参考

本文档记录当前项目的 Live2D 控制方式，并作为后续扩展到 UE、Pixel Streaming、WebRTC 或视频流数字人的参考。

## 当前控制通道

前端与后端主要通过 WebSocket 通信：

```text
ws://localhost:12393/client-ws
```

Live2D 相关控制不是独立 REST API，而是作为 WebSocket 消息的一部分下发。

## 模型加载与切换

后端发送 `set-model-and-conf` 消息给前端：

```json
{
  "type": "set-model-and-conf",
  "model_info": {
    "name": "mao_pro",
    "url": "/live2d-models/mao_pro/runtime/mao_pro.model3.json",
    "kScale": 0.5,
    "initialXshift": 0,
    "initialYshift": 0,
    "kXOffset": 1150,
    "idleMotionGroupName": "Idle",
    "emotionMap": {
      "neutral": 0,
      "anger": 2,
      "disgust": 2,
      "fear": 1,
      "joy": 3,
      "smirk": 3,
      "sadness": 1,
      "surprise": 3
    },
    "tapMotions": {}
  },
  "conf_name": "mao_pro",
  "conf_uid": "mao_pro_001",
  "client_uid": "..."
}
```

关键字段：

- `model_info.name`：模型名称。
- `model_info.url`：Live2D `.model3.json` 路径。
- `model_info.emotionMap`：文本情绪标签到前端表情索引的映射。
- `conf_name`：当前角色配置显示名。
- `conf_uid`：当前角色唯一 ID。

相关文件：

- `src/open_llm_vtuber/websocket_handler.py`
- `src/open_llm_vtuber/service_context.py`
- `model_dict.json`

## 语音、字幕与表情控制

AI 回复经过 TTS 后，后端发送 `audio` 消息：

```json
{
  "type": "audio",
  "audio": "<base64 wav>",
  "volumes": [0.1, 0.3, 0.8],
  "slice_length": 20,
  "display_text": {
    "text": "你好",
    "name": "AI",
    "avatar": "mao.png"
  },
  "actions": {
    "expressions": [3]
  },
  "forwarded": false
}
```

关键字段：

- `audio`：base64 编码的 WAV 音频。为空时可用于静默字幕/动作。
- `volumes`：按 `slice_length` 分片的归一化音量，用于嘴型或音量驱动。
- `slice_length`：每个音量分片的毫秒数，当前默认 20ms。
- `display_text`：前端字幕和聊天显示内容。
- `actions.expressions`：表情索引列表。

表情索引来自 `model_dict.json` 的 `emotionMap`。例如：

```json
{
  "joy": 3,
  "sadness": 1
}
```

当 LLM 输出：

```text
[joy] 你好
```

后端会提取为：

```json
{
  "actions": {
    "expressions": [3]
  }
}
```

相关文件：

- `src/open_llm_vtuber/agent/transformers.py`
- `src/open_llm_vtuber/live2d_model.py`
- `src/open_llm_vtuber/utils/stream_audio.py`
- `src/open_llm_vtuber/conversations/tts_manager.py`
- `src/open_llm_vtuber/conversations/conversation_utils.py`
- `src/open_llm_vtuber/utils/sentence_divider.py`

## TTS 分句规则

LLM 流式输出进入 TTS 前会经过 `SentenceDivider` 分句。分句器需要兼顾低延迟和口播完整性：

- `pysbd` 和 regex 两种分句路径都需要保护数字小数点。
- `1.2万亿元`、`3.5%` 这类数字不能因为中间的 `.` 被拆成两段 TTS。
- 流式输出中如果当前缓冲只收到 `1.`，分句器会先保留这段文本，等待后续 token；只有确认不是小数后，才会按句号分段。
- 独立 `/tts-ws` 路由也复用同一套 regex 分句逻辑，避免直接 `text.split(".")` 破坏小数。

示例：

```text
今年投资达到1.2万亿元。同比增长明显。
```

会拆成：

```text
今年投资达到1.2万亿元。
同比增长明显。
```

不会拆成 `今年投资达到1.` 和 `2万亿元。`。

## 前端 Live2D Adapter 能力

前端暴露：

```js
window.getLAppAdapter()
```

可用能力包括：

```js
getModel()
startMotion(group, index, priority, onFinished)
setExpression(index)
setChara(basePath, modelName)
getExpressionCount()
getExpressionName(index)
getMotionGroups()
getMotionCount(group)
setModelPosition(x, y)
getModelPosition()
```

当前后端协议主要使用：

- `set-model-and-conf`：切换模型和角色配置。
- `audio.actions.expressions`：控制表情。
- `audio.volumes`：驱动嘴型/音量表现。

## 扩展到 UE 数字人

推荐把 UE 当作“数字人渲染引擎”，Web/Open-LLM-VTuber 保持负责：

- ASR
- LLM
- TTS
- MCP
- 聊天历史
- 设置界面
- 角色配置

UE 负责：

- MetaHuman 或 3D 数字人渲染
- 表情
- 动画
- 镜头
- 灯光
- 嘴型

建议新增一个 UE 控制桥接层，监听现有 WebSocket 消息并转换为 UE 可理解的控制命令。

### 建议映射

`set-model-and-conf` 可映射为：

```json
{
  "type": "avatar.load",
  "avatar_id": "metahuman_default",
  "profile_id": "mao_pro_001",
  "display_name": "mao_pro"
}
```

`audio` 可映射为：

```json
{
  "type": "avatar.speak",
  "audio": "<base64 wav>",
  "volumes": [0.1, 0.3, 0.8],
  "slice_length": 20,
  "text": "你好",
  "expressions": ["joy"]
}
```

推荐提问/追问使用独立 UI 消息，不参与语音合成：

```json
{
  "Topic": "human",
  "Data": {
    "Key": "suggestions",
    "Value": [
      "今日负荷高峰预计何时出现？",
      "是否存在设备过载风险？",
      "有哪些重点区域需要关注？"
    ],
    "Context": "follow_up"
  },
  "Username": "User"
}
```

后端在一轮回答完成后基于用户问题与完整回答生成 `follow_up`；初始示例问题可通过 `POST /api/runtime/ue-suggestions` 生成 `initial`。UE 侧只刷新推荐按钮，点击后按普通文本输入发送。

如果 UE 侧使用索引而不是名称，也可以继续使用当前的 `expressions: [3]`。更推荐在桥接层把索引还原为语义标签，例如 `joy`、`sadness`、`anger`，这样 UE、VRM、Live2D 可以各自维护自己的表情映射。

### UE 侧建议接口

UE 可以通过以下方式接收控制：

- WebSocket 客户端连接到本地桥接服务。
- HTTP 本地接口接收控制命令。
- Pixel Streaming Data Channel 接收浏览器转发的控制消息。
- OSC/UDP 用于低延迟动作控制。

推荐优先使用 WebSocket 或 Pixel Streaming Data Channel，便于和现有网页架构整合。

## Pixel Streaming 方案

Pixel Streaming 中，UE 负责渲染并通过 WebRTC 输出画面。网页中可以把 UE 画面作为一个区域嵌入，同时保留 Web UI。

推荐结构：

```text
Open-LLM-VTuber Web UI
  ├─ Pixel Streaming 区域：显示 UE/MetaHuman
  ├─ 聊天与字幕区域
  ├─ 设置面板
  └─ 角色/MCP/历史记录

Open-LLM-VTuber 后端
  ├─ ASR
  ├─ LLM
  ├─ TTS
  ├─ MCP
  └─ 控制消息

UE
  ├─ MetaHuman 渲染
  ├─ 表情/动作
  ├─ 嘴型
  └─ Pixel Streaming 输出
```

控制方向：

```text
后端 -> 网页 -> Pixel Streaming Data Channel -> UE
```

或：

```text
后端 -> 本地 UE 控制桥 -> UE
```

两者都可行。若网页已经集成 Pixel Streaming，走 Data Channel 更自然。若 UE 和后端在同一台机器，走本地控制桥更简单。

## 视频流数字人方案

如果数字人由外部程序渲染并输出视频流，可以复用同一套抽象：

- `avatar.load`：切换外部场景/角色。
- `avatar.speak`：播放音频、驱动嘴型。
- `avatar.expression`：设置表情。
- `avatar.motion`：播放动作。
- `avatar.idle`：进入待机。

视频流可以通过：

- WebRTC
- OBS WebRTC/WHIP
- RTMP/HLS
- 本地窗口采集

实时对话优先选择 WebRTC。RTMP/HLS 延迟通常过高，更适合直播给观众看，不适合交互聊天。

## 建议的通用 Avatar 协议

为了同时支持 Live2D、UE、VRM、视频流数字人，建议未来在现有消息上增加一个更通用的动作层：

```json
{
  "type": "avatar-control",
  "target": "primary",
  "command": "expression",
  "payload": {
    "name": "joy",
    "intensity": 1.0,
    "duration_ms": 1200
  }
}
```

说话：

```json
{
  "type": "avatar-control",
  "target": "primary",
  "command": "speak",
  "payload": {
    "audio": "<base64 wav>",
    "text": "你好",
    "volumes": [0.1, 0.3, 0.8],
    "slice_length": 20,
    "expressions": ["joy"]
  }
}
```

动作：

```json
{
  "type": "avatar-control",
  "target": "primary",
  "command": "motion",
  "payload": {
    "name": "wave",
    "priority": 2
  }
}
```

这层协议可以由不同渲染器各自实现：

- Live2D：映射到 `setExpression(index)` 和 `startMotion(...)`。
- UE/MetaHuman：映射到 Animation Blueprint、Control Rig、Pose Asset、Audio2Face 或 MetaHuman Animator 管线。
- VRM：映射到 blendshape、humanoid bone animation、viseme。
- 视频流数字人：映射到外部程序 API 或 Data Channel。

## 当前限制

当前项目原生支持的是 Live2D。UE、VRM、视频流数字人需要新增前端/桥接层或外部控制服务。

当前 `actions` 数据结构支持：

```python
expressions
pictures
sounds
```

但现有主链路主要使用 `expressions`。如果要扩展动作、手势、镜头、姿态，建议扩展 `Actions` 或新增独立的 `avatar-control` 消息类型。
