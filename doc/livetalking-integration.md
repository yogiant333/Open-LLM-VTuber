# LiveTalking 视频流数字人接入分析

目标项目：

```text
D:\AI\LiveTalking
/mnt/d/AI/LiveTalking
```

本文档记录 LiveTalking 的接口形态，以及它接入当前 Open-LLM-VTuber 的推荐方案。

## LiveTalking 能力概览

LiveTalking 是视频流数字人服务，支持：

- WebRTC 输出
- RTMP 输出
- 虚拟摄像头输出
- wav2lip / musetalk / ultralight 等数字人模型
- 文本驱动数字人说话
- 音频文件驱动数字人说话
- 打断当前说话
- 多 session

当前本地目录中已有模型和 avatar：

```text
/mnt/d/AI/LiveTalking/models/wav2lip.pth
/mnt/d/AI/LiveTalking/data/avatars/wav2lip256_avatar1
/mnt/d/AI/LiveTalking/data/avatars/shuziren_wav2lip256
```

## LiveTalking 启动方式

README 推荐的基础启动命令：

```bash
cd /mnt/d/AI/LiveTalking
python app.py --transport webrtc --model wav2lip --avatar_id wav2lip256_avatar1
```

默认监听端口：

```text
8010
```

默认页面：

```text
http://localhost:8010/dashboard.html
http://localhost:8010/webrtcapi.html
```

如果走 WebRTC，需要浏览器能访问 LiveTalking 服务。跨机器访问时还要考虑 UDP、STUN/TURN、防火墙和代理。

## LiveTalking 核心接口

### 建立 WebRTC 视频流

接口：

```text
POST http://localhost:8010/offer
```

请求体来自浏览器 `RTCPeerConnection.createOffer()`：

```json
{
  "sdp": "<browser offer sdp>",
  "type": "offer",
  "avatar": "wav2lip256_avatar1",
  "use_stun": false
}
```

响应：

```json
{
  "sdp": "<server answer sdp>",
  "type": "answer",
  "sessionid": "..."
}
```

`sessionid` 后续用于控制这个数字人会话。

相关代码：

```text
/mnt/d/AI/LiveTalking/server/rtc_manager.py
/mnt/d/AI/LiveTalking/frontend/src/main.jsx
```

### 文本驱动说话

接口：

```text
POST http://localhost:8010/human
```

请求：

```json
{
  "text": "你好，我是数字人。",
  "type": "echo",
  "interrupt": true,
  "sessionid": "<offer 返回的 sessionid>"
}
```

模式：

- `type: "echo"`：直接朗读输入文本。
- `type: "chat"`：LiveTalking 自己调用它的 LLM，再朗读回复。

和 Open-LLM-VTuber 对接时，推荐只用 `echo`，让 Open-LLM-VTuber 负责 LLM，LiveTalking 只负责数字人渲染和口型。

相关代码：

```text
/mnt/d/AI/LiveTalking/server/routes.py
```

### 音频文件驱动说话

接口：

```text
POST http://localhost:8010/humanaudio
```

表单字段：

- `sessionid`
- `file`

用途：把外部 TTS 生成的音频直接送给 LiveTalking 做口型和播放。

这和 Open-LLM-VTuber 的现有协议最匹配，因为 Open-LLM-VTuber 的 `audio` WebSocket 消息里已经包含 base64 WAV。

### 打断说话

接口：

```text
POST http://localhost:8010/interrupt_talk
```

请求：

```json
{
  "sessionid": "<sessionid>"
}
```

### 查询是否正在说话

接口：

```text
POST http://localhost:8010/is_speaking
```

请求：

```json
{
  "sessionid": "<sessionid>"
}
```

## 当前 Open-LLM-VTuber 输出协议

Open-LLM-VTuber 的主 WebSocket：

```text
ws://localhost:12393/client-ws
```

AI 回复后会向前端发送：

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

其中 `audio` 可以转成 WAV 文件/Blob，提交到 LiveTalking 的 `/humanaudio`。

## 推荐接入方案

推荐方案：**网页端双连接编排**。

```text
浏览器页面
  ├─ 连接 Open-LLM-VTuber ws://localhost:12393/client-ws
  ├─ 连接 LiveTalking WebRTC http://localhost:8010/offer
  ├─ 显示 LiveTalking 返回的视频流
  ├─ 用户输入发送给 Open-LLM-VTuber
  └─ 收到 Open-LLM-VTuber audio 消息后转发音频到 LiveTalking /humanaudio
```

流程：

1. 页面加载。
2. 前端创建 `RTCPeerConnection`。
3. 调用 LiveTalking `/offer`。
4. 保存 LiveTalking 返回的 `sessionid`。
5. 页面连接 Open-LLM-VTuber `/client-ws`。
6. 用户文本/语音进入 Open-LLM-VTuber。
7. Open-LLM-VTuber 返回 `audio` 消息。
8. 前端把 `audio` base64 转成 WAV Blob。
9. 前端用 multipart/form-data 调 LiveTalking `/humanaudio`。
10. LiveTalking 生成口型视频，通过 WebRTC 流显示数字人。

## 为什么推荐前端双连接

LiveTalking 的 `sessionid` 是 `/offer` 时针对浏览器 WebRTC 会话创建的。这个 session 本质属于前端连接。

如果后端直接转发音频给 LiveTalking，需要让 Open-LLM-VTuber 后端知道浏览器对应的 LiveTalking `sessionid`，还要维护多用户映射，复杂度更高。

前端双连接更直接：

- LiveTalking session 生命周期由浏览器管理。
- Open-LLM-VTuber 不需要知道 LiveTalking 内部 session。
- 可以逐步替换当前 Live2D 渲染层。
- 对多用户更自然。

## 最小前端桥接伪代码

建立 LiveTalking WebRTC：

```js
const pc = new RTCPeerConnection({ sdpSemantics: "unified-plan" });
pc.addTransceiver("video", { direction: "recvonly" });
pc.addTransceiver("audio", { direction: "recvonly" });

pc.addEventListener("track", (event) => {
  if (event.track.kind === "video") videoEl.srcObject = event.streams[0];
  if (event.track.kind === "audio") audioEl.srcObject = event.streams[0];
});

const offer = await pc.createOffer();
await pc.setLocalDescription(offer);

const response = await fetch("http://localhost:8010/offer", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    sdp: pc.localDescription.sdp,
    type: pc.localDescription.type,
    avatar: "wav2lip256_avatar1",
    use_stun: false
  })
});

const answer = await response.json();
const livetalkingSessionId = answer.sessionid;
await pc.setRemoteDescription(answer);
```

把 Open-LLM-VTuber 音频转发给 LiveTalking：

```js
async function sendOpenLLMVtuberAudioToLiveTalking(message) {
  if (message.type !== "audio" || !message.audio) return;

  const bytes = Uint8Array.from(atob(message.audio), (c) => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: "audio/wav" });

  const form = new FormData();
  form.append("sessionid", livetalkingSessionId);
  form.append("file", blob, "reply.wav");

  await fetch("http://localhost:8010/humanaudio", {
    method: "POST",
    body: form
  });
}
```

如果只想让 LiveTalking 自己 TTS，可以转发文本：

```js
await fetch("http://localhost:8010/human", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    text: message.display_text.text,
    type: "echo",
    interrupt: true,
    sessionid: livetalkingSessionId
  })
});
```

但这样会重复使用 LiveTalking 的 TTS，声音配置会和 Open-LLM-VTuber 分离。优先推荐 `/humanaudio`。

## UI 接入方式

当前 Open-LLM-VTuber 前端是已构建的子模块资源，不适合直接在产物上硬改。

建议两条路线：

### 路线 A：新建独立桥接页面

新增一个页面，例如：

```text
web_tool/livetalking_bridge.html
```

这个页面负责：

- 连接 LiveTalking WebRTC。
- 连接 Open-LLM-VTuber WebSocket。
- 显示 LiveTalking 视频。
- 保留最小聊天输入框。
- 把 Open-LLM-VTuber 的音频转发给 `/humanaudio`。

优点：

- 改动小。
- 不影响现有 Live2D 前端。
- 适合快速验证。

缺点：

- UI 和当前主界面不是同一个 React 应用。

### 路线 B：改 Open-LLM-VTuber 前端源码

在前端新增渲染模式：

```text
avatar_renderer: live2d | livetalking
```

当选择 `livetalking` 时：

- 隐藏 Live2D canvas。
- 显示 LiveTalking WebRTC video。
- 收到 `audio` 消息后不走 Live2D 嘴型，而是提交到 `/humanaudio`。

优点：

- 集成体验最好。
- 可以复用主界面的设置、聊天历史、MCP、角色切换。

缺点：

- 需要维护前端源码和构建流程。
- 需要处理跨域、连接状态、断线重连、session 清理。

## 后端桥接方案

也可以在 Open-LLM-VTuber 后端新增 LiveTalking bridge：

```text
Open-LLM-VTuber 后端收到 TTS audio
  -> POST /humanaudio 到 LiveTalking
```

但这需要新增一个“浏览器 client_uid -> LiveTalking sessionid”的映射。

前端在 `/offer` 成功后，需要把 `sessionid` 注册给 Open-LLM-VTuber 后端：

```json
{
  "type": "register-external-avatar",
  "provider": "livetalking",
  "sessionid": "..."
}
```

然后后端才能知道该把音频发给哪个 LiveTalking session。

这个方案适合产品化，但不是最快验证路径。

## 和 UE/Pixel Streaming 的关系

LiveTalking 的接法和 UE Pixel Streaming 类似：

- 都有一个浏览器视频区域。
- 都需要一个外部渲染/流媒体 session。
- 都需要把 Open-LLM-VTuber 的文本、音频、表情事件映射到外部数字人引擎。

区别：

- LiveTalking 已经提供 `/human` 和 `/humanaudio`。
- UE/Pixel Streaming 通常需要自己定义 Data Channel 或本地 WebSocket 控制协议。

所以 LiveTalking 可以作为“视频流数字人接入”的低成本验证样板。

## 推荐第一阶段实现

第一阶段先做独立桥接页面，不改主前端：

1. 启动 Open-LLM-VTuber：

```bash
cd /mnt/d/AI/Open-LLM-VTuber
uv run run_server.py
```

2. 启动 LiveTalking：

```bash
cd /mnt/d/AI/LiveTalking
python app.py --transport webrtc --model wav2lip --avatar_id wav2lip256_avatar1
```

3. 打开桥接页。

4. 桥接页建立 LiveTalking WebRTC。

5. 桥接页连接 Open-LLM-VTuber WebSocket。

6. 用户输入走 Open-LLM-VTuber。

7. Open-LLM-VTuber 返回音频后，桥接页转发到 LiveTalking `/humanaudio`。

8. LiveTalking 视频流播放数字人。

第一阶段不处理复杂表情映射，只处理：

- 文本
- 音频
- 打断
- 视频显示

第二阶段再处理：

- 角色选择联动 avatar
- 表情标签到 LiveTalking 动作状态
- 字幕同步
- 说话状态同步
- 错误恢复
- 多用户 session 映射
