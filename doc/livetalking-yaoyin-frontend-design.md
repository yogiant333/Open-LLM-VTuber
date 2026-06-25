# LiveTalking 瑶音数字人前端设计分析

## 目标

基于 B 站参考视频《有一位飞天数字人从壁画中走来，她叫瑶音》分析画面风格，并设计一个前端页面：用 LiveTalking 的 WebRTC 输出承载数字人视频流，用 Open-LLM-VTuber 现有对话链路负责 ASR/LLM/TTS。

本阶段只做分析设计，不进入实现。

## 素材与下载结果

参考链接：

```text
https://www.bilibili.com/video/BV1yJLD6xEM3
```

B 站元信息：

- 标题：有一位飞天数字人从壁画中走来，她叫瑶音
- BV：BV1yJLD6xEM3
- CID：39180962124
- 时长：253.655 秒
- 原始标称画幅：1440 x 2560，竖屏 9:16
- 匿名可抓取 DASH 流：480 x 852，约 30fps
- 平台标记：含 AI 生成内容

本地分析资产：

```text
reports/livetalking-yaoyin-video/yaoyin-reference.mp4
reports/livetalking-yaoyin-video/timeline-contact.jpg
reports/livetalking-yaoyin-video/frames/frame_001.jpg ... frame_051.jpg
```

说明：匿名接口只返回低清 DASH 流，足够做布局、色彩、镜头和信息层级分析；如果后续要做像素级复刻，需要使用登录 Cookie 或原始素材。

## 视频画面分析

### 总体结构

视频是典型的展厅/宣传屏数字人界面，而不是剧情短片。

主画面长期保持：

- 竖屏 9:16。
- 黑色或近黑背景，避免干扰数字人轮廓。
- 中央全身数字人，身体从头饰到鞋完整露出。
- 左上角展示时间、天气/地理类状态。
- 左侧中上区域展示问答/知识点列表。
- 右上区域展示数字人介绍或功能说明。
- 右中部有醒目的黄色提示气泡。
- 底部有字幕条、品牌署名、B 站水印。
- 后半段增加青绿色大段文本框，类似讲解稿/知识卡片。

### 数字人视觉

角色是敦煌飞天/古风女性形象：

- 服饰为橙金、青蓝、浅白纱袖组合。
- 头饰较复杂，强化文化主题和识别度。
- 人物肤色和服装高亮度明显高于背景。
- 人物居中，比例约占画面宽度 45%-55%，高度约占 85%-92%。
- 动作幅度低，主要是微笑、嘴型、手臂开合、轻微站姿变化。

对 LiveTalking 落地的启发：

- 页面应把数字人视频作为主视觉，而不是放在普通卡片里。
- LiveTalking 视频容器优先使用 `object-fit: contain`，确保全身不被裁切。
- 黑色舞台背景和轻量信息层叠加比复杂 UI 更适合这种数字人。
- 如使用 wav2lip/musetalk 半身素材，页面应提供“全身素材模式”和“半身对话模式”两种构图策略。

### 信息层级

画面信息分三层：

1. 主体层：中央数字人。
2. 导览层：顶部状态、左右知识面板、提示气泡。
3. 对话层：底部字幕、临时回答、长文本解释框。

信息密度较高，但布局稳定。用户注意力先看数字人，再看黄色提示/底部字幕，最后看左右面板。

前端页面应保留稳定的信息区域，不要让聊天消息无限挤压舞台。

### 色彩与字体

主要色彩：

- 背景：黑色、深灰。
- 主强调：青绿色，用于标题、字幕和知识卡片。
- 次强调：黄色，用于提示气泡。
- 人物色：橙金、青蓝、白纱。
- 文本：白色和浅灰。

字体风格偏展示屏，不需要过度装饰。UI 字号要分层：

- 顶部状态：12-14px。
- 面板标题：14-16px，青绿色。
- 面板正文：12-14px，白/浅灰。
- 底部字幕：14-16px。
- 用户输入区：14-16px。

### 动作与状态

时间轴抽帧显示，视频主要是单镜头连续讲解：

- 开场：数字人正立，左右说明面板已经出现。
- 中段：手势展开，形成欢迎/讲解状态。
- 后段：底部出现更密集的青绿色文本框，承载长回答。
- 结尾：仍保持同一舞台构图。

因此页面状态不需要复杂切镜头，重点是：

- 空闲：数字人居中，显示欢迎提示。
- 连接中：舞台半透明遮罩 + 状态提示。
- 聆听：麦克风/波形轻量反馈。
- 思考：底部状态条显示“正在生成回答”。
- 说话：字幕同步显示，必要时右侧显示本轮回答摘要。
- 中断：清除待播音频，调用 LiveTalking `/interrupt_talk`。

## LiveTalking WebRTC 能力约束

LiveTalking 官方文档说明：

- 支持 `wav2lip`、`musetalk`、`ernerf`、`Ultralight-Digital-Human` 等模型。
- 默认传输方式支持 WebRTC，服务常见端口为 TCP 8010；P2P WebRTC 还涉及 UDP 端口。
- `/offer` 用于 WebRTC 协商，返回 `answer` 和 `sessionid`。
- `/human` 用于文本驱动说话。
- `/interrupt_talk` 用于打断当前说话。

参考：

```text
https://livetalking-doc.readthedocs.io/en/latest/usage.html
https://livetalking-doc.readthedocs.io/en/latest/api.html
```

当前仓库已有 LiveTalking 客户端：

```text
frontend/src/renderer/src/services/livetalking-client.ts
frontend/src/renderer/src/context/avatar-renderer-context.tsx
frontend/src/renderer/src/components/console/digital-human-stage.tsx
frontend/src/renderer/src/components/console/digital-human-settings.tsx
```

现有实现已经覆盖：

- 创建 `RTCPeerConnection`。
- POST `/offer` 建立 WebRTC。
- 保存 `sessionid`。
- 将 Open-LLM-VTuber 的 base64 WAV 转 Blob。
- POST `/humanaudio` 给 LiveTalking。
- POST `/interrupt_talk` 打断。
- 在舞台里显示 LiveTalking `MediaStream`。

因此设计重点不是从零接入，而是把现有 LiveTalking 模式整理成一个更像参考视频的数字人页面。

## 页面设计方案

### 页面定位

新增或改造一个“展厅数字人模式”页面，适合本机或大屏展示：

```text
http://127.0.0.1:3000/
```

目标体验：

- 第一屏就是数字人舞台。
- 用户不用理解 Live2D/UE/LiveTalking 技术名词。
- 连接状态、字幕、输入、打断都在同一屏完成。
- 可在设置中保留高级参数，但默认界面只暴露必要操作。

### 布局

桌面端推荐 16:9 页面中放置竖屏舞台：

```text
┌────────────────────────────────────────────────────────────┐
│ 顶栏：时间 / 天气 / 连接状态 / 设置                         │
├───────────────┬──────────────────────────┬─────────────────┤
│ 知识/会话面板 │  9:16 LiveTalking 舞台    │  能力/提示面板  │
│               │  中央数字人视频流         │                 │
│               │  底部字幕                 │                 │
├───────────────┴──────────────────────────┴─────────────────┤
│ 输入区：文本框 / 麦克风 / 发送 / 打断                         │
└────────────────────────────────────────────────────────────┘
```

移动端/竖屏大屏推荐直接全屏竖屏舞台：

```text
┌────────────────────┐
│ 顶部状态            │
│ 左右信息折叠为浮层   │
│                    │
│ LiveTalking video  │
│                    │
│ 字幕 / 回答卡片      │
│ 输入 / 麦克风 / 打断 │
└────────────────────┘
```

### 视觉规格

- 舞台背景：`#050607` 或透明黑渐变。
- 主强调色：青绿色 `#20D6C7`。
- 警示/提示色：黄色 `#FFD84A`。
- 辅助文本：`#D7DEE8`。
- 面板背景：黑色 70%-85% 透明度。
- 卡片半径：6-8px。
- 数字人视频：不加装饰卡片，使用舞台中央的真实视频区域。
- 左右信息面板不要遮住人物脸和上半身；最多压到背景空白区。

### 核心组件

建议组件拆分：

```text
DigitalHumanShowcasePage
  ├─ ShowcaseTopBar
  ├─ LiveTalkingStage
  │   ├─ LiveTalkingVideoSurface
  │   ├─ StageStatusOverlay
  │   ├─ SubtitleBar
  │   └─ SpeakingWaveform
  ├─ KnowledgePanel
  ├─ PromptBubble
  ├─ AnswerCard
  └─ ConversationControls
```

当前 `DigitalHumanStage` 可作为基础，但需要去掉调试感较强的模式切换按钮，改成展示模式。

### 交互流程

1. 页面加载后读取默认 LiveTalking 配置。
2. 自动尝试连接 LiveTalking `/offer`。
3. 如果连接失败，舞台显示“连接 LiveTalking”按钮和错误原因。
4. 用户输入文本或语音。
5. 前端把输入发给 Open-LLM-VTuber WebSocket。
6. 后端完成 ASR/LLM/TTS。
7. 前端收到 `audio` 消息。
8. LiveTalking 模式下，前端把音频提交到 `/humanaudio`。
9. LiveTalking 通过 WebRTC 推回数字人音视频。
10. 前端底部同步显示 `display_text.text`。
11. 用户点击打断时，前端同时打断本项目对话链路和 LiveTalking `/interrupt_talk`。

### 状态机

```text
disconnected
  -> connecting
  -> ready
  -> listening
  -> thinking
  -> speaking
  -> ready

任意状态 -> error
任意说话/思考状态 -> interrupted -> ready
```

状态文案面向用户，不暴露底层协议：

- `connecting`：正在连接数字人
- `ready`：可以开始对话
- `listening`：正在听你说
- `thinking`：正在组织回答
- `speaking`：正在讲解
- `error`：数字人连接异常

### 字幕与长回答

参考视频中字幕是数字人可信度的重要部分。建议：

- 短句走底部字幕条。
- 超过 80 字的回答同时进入右下或底部青绿色回答卡。
- 字幕最多两行，避免挡住人物衣服细节。
- 回答卡只显示当前轮，历史对话放左侧面板或抽屉。

### LiveTalking 模型素材建议

如果目标是复现参考视频的“全身飞天数字人”，LiveTalking avatar 素材应优先准备：

- 竖屏全身静默视频，人物嘴闭合或少口型变化。
- 背景尽量纯黑或可抠图。
- 服饰和头饰边缘要清晰，避免纱袖被低码率压坏。
- 使用 25/30fps，时长至少 5-10 秒，包含自然眨眼和轻微手势更好。

模型选择建议：

- 快速验证：`wav2lip`，成本低，但更适合口型驱动，动作有限。
- 更好观感：`musetalk` 或 LiveTalking 支持的更高质量模型。
- 全身动作/固定讲解视频：评估 LiveTalking 的 action choreography / custom video 能力。

## 与现有前端的落地路径

### 阶段 1：展示页外观改造

改造范围：

```text
frontend/src/renderer/src/components/console/digital-human-stage.tsx
frontend/src/renderer/src/components/console/digital-human-settings.tsx
frontend/src/renderer/src/context/avatar-renderer-context.tsx
frontend/src/renderer/src/locales/zh/translation.json
frontend/src/renderer/src/locales/en/translation.json
```

目标：

- 保留现有 LiveTalking 连接能力。
- 新增展示模式布局。
- 默认优先显示 LiveTalking 舞台。
- 让连接按钮、状态、字幕更像展厅数字人页面。

### 阶段 2：对话输入和字幕同步

目标：

- 将当前 `audio` 消息里的 `display_text.text` 显示到舞台字幕。
- 将当前用户输入/ASR 文本显示在左侧“访客提问”。
- 将 LLM 回复摘要显示到右下回答卡。
- 打断时清空字幕和待播状态。

### 阶段 3：素材和动作增强

目标：

- 准备“瑶音风格”竖屏全身 LiveTalking avatar。
- 对接 `/set_audiotype` 或 custom video，支持欢迎、讲解、空闲三类动作。
- 增加空闲微动、手势状态、讲解手势切换。

## 验收标准

功能验收：

- 页面能连接 `http://127.0.0.1:18010/offer` 或配置的 LiveTalking 地址。
- LiveTalking WebRTC 视频能显示在舞台中央。
- Open-LLM-VTuber 返回的 TTS 音频能转发到 LiveTalking `/humanaudio`。
- 点击打断能停止当前数字人说话。
- 断开 LiveTalking 时页面有明确状态，不白屏。

视觉验收：

- 1366x768、1920x1080、移动竖屏下无文字重叠。
- 数字人全身不被裁切。
- 字幕不遮挡脸部和核心手势。
- 黑底、青绿、黄色提示形成参考视频同类的视觉记忆点。
- 交互控件不抢数字人主体视觉。

工程验收：

- 前端改动后运行 `npm run typecheck` 或项目现有类型检查命令。
- 运行前端开发服务，使用 Playwright 检查页面截图。
- 连接失败、连接成功、发送音频、打断四种状态均有手动验证记录。

## 风险

- 参考视频是宣传成片，不代表 LiveTalking 实时输出的动作质量。
- 匿名下载素材分辨率低，不能直接作为高质量 avatar 训练素材。
- WebRTC P2P 在跨机器场景需要 UDP、防火墙、STUN/TURN 配置。
- LiveTalking `/humanaudio` 不在旧版官方 API 文档显式列出，但当前仓库已有客户端按该接口实现；需要以本地 LiveTalking 实例实测为准。
- 现有前端已有 LiveTalking 模式，后续实现应优先整理和复用，不要另起一套重复连接逻辑。
