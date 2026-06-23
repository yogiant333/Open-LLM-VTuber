# ASR 网页测试台设计

## 目标

在当前 Open-LLM-VTuber 项目里增加一个轻量网页工具，用浏览器麦克风录制同一段真实环境音频，并行送给多个 ASR 后端，直观看出不同 ASR 在当前电脑、麦克风、展厅噪声、热词配置下的准确率和速度差异。

首版重点解决两个问题：

- 同一段音频下，各 ASR 最终识别文本有什么差异。
- 各 ASR 的总耗时、RTF 和热词命中情况如何。

首版不做真正流式 partial 对比。流式 ASR 的分段策略、VAD 策略和 partial 语义差异较大，直接比较容易误判。先做“录音完成后并行评测”更公平，也更容易稳定复现。

## 使用方式

入口：

- `/asr-benchmark`
- `/asr-benchmark/index.html`

用户流程：

1. 打开网页。
2. 勾选要测试的 ASR，例如 `qwen3_asr`、`faster_whisper`、`sherpa_onnx_asr`。
3. 可编辑热词列表，例如 `小智`、`孟昭泰`、`迎峰度夏`、`售电量`。
4. 点击录音，说一句测试语音。
5. 停止录音后，浏览器把同一段 WAV 发给后端。
6. 后端并行调用多个 ASR。
7. 页面展示每个 ASR 的结果文本、耗时、RTF、热词命中和错误信息。
8. 用户可填写参考文本，页面计算 CER/WER。

## 页面布局

页面使用普通静态 HTML/CSS/JS，放在 `web_tool/asr_benchmark/`，沿用项目现有 `web_tool` 静态工具模式，不引入新前端工程。

主要区域：

- 顶部工具栏：后端状态、麦克风权限、采样率、录音时长。
- ASR 选择区：复选框列表，显示可用 ASR 和是否可初始化。
- 热词区：多行文本框，一行一个热词。
- 录音区：录制、停止、重放、上传 WAV。
- 参考文本区：人工输入标准答案。
- 结果表格：每个 ASR 一行。

结果表字段：

- `ASR`
- `状态`
- `识别文本`
- `音频时长 ms`
- `总耗时 ms`
- `RTF`
- `热词命中`
- `CER`
- `WER`
- `错误`

RTF 计算：

```text
RTF = asr_elapsed_ms / audio_duration_ms
```

小于 1 表示识别速度快于实时。

## 后端接口

### 获取可测试 ASR

`GET /api/asr-benchmark/providers`

返回：

```json
{
  "current_asr": "qwen3_asr",
  "hotwords": ["小智", "孟昭泰", "迎峰度夏"],
  "providers": [
    {
      "name": "qwen3_asr",
      "enabled": true,
      "available": true,
      "reason": "",
      "supports_hotwords": true,
      "mode": "context"
    }
  ]
}
```

`available` 只做轻量检查，不强制加载所有模型。比如：

- `qwen3_asr`：检查 `qwen_asr` 包、CUDA 是否可用、配置是否存在。
- `faster_whisper`：检查包是否可 import、配置是否存在。
- `sherpa_onnx_asr`：检查包和模型路径是否存在。

### 并行评测

`POST /api/asr-benchmark/transcribe`

请求使用 `multipart/form-data`：

- `file`: WAV 文件，16 kHz mono PCM 优先。
- `providers`: JSON 字符串，例如 `["qwen3_asr","faster_whisper"]`。
- `hotwords`: JSON 字符串，一行热词解析后的数组。
- `reference_text`: 可选，用于后端也计算 CER/WER。

返回：

```json
{
  "audio": {
    "duration_ms": 2380,
    "sample_rate": 16000,
    "channels": 1
  },
  "results": [
    {
      "provider": "qwen3_asr",
      "text": "迎峰度夏重点是什么？",
      "elapsed_ms": 1180,
      "rtf": 0.496,
      "hotword_hits": ["迎峰度夏"],
      "cer": 0.0,
      "wer": 0.0,
      "error": null
    }
  ]
}
```

### 单个 ASR 测试

`POST /api/asr-benchmark/transcribe/{provider}`

用于页面重跑某一行，不必重新评测全部 ASR。

## ASR 初始化策略

不能复用当前对话主 ASR 作为唯一测试对象，因为测试台需要同时比较多个 ASR。设计为新增一个轻量管理器：

`src/open_llm_vtuber/asr/benchmark.py`

职责：

- 从当前 `conf.yaml` 读取 ASR 配置。
- 按 provider 名称创建独立 ASR 实例。
- 缓存已加载实例，避免每次请求重复加载模型。
- 给每次请求注入临时热词，但不写回 `conf.yaml`。
- 控制并发，避免同时加载多个大模型导致显存爆掉。

缓存策略：

- 当前主 ASR 是 `qwen3_asr` 时，优先复用 `default_context_cache.asr_engine`，避免重复占用 GPU。
- 其他 ASR 按需加载并缓存。
- 提供后续可选接口清理缓存：`POST /api/asr-benchmark/cache/clear`。

并发策略：

- 同一段音频的多个 ASR 可以并行执行。
- 但 GPU 型 ASR 默认串行或限制并发为 1，避免显存峰值和推理互相拖慢。
- CPU/远程 HTTP ASR 可以并行。

首版简单实现：

- `qwen3_asr` 单独一个 GPU 锁。
- 其他 ASR 使用 `asyncio.gather` 并行。

## 热词设计

已经有公共热词配置：

```yaml
character_config:
  asr_config:
    hotwords:
      - 小智
      - 孟昭泰
      - 迎峰度夏
```

测试台的热词来源：

1. 默认读取 `conf.yaml` 的 `asr_config.hotwords`。
2. 页面允许临时编辑。
3. 临时热词只作用于本次评测，不自动写回配置。

各 ASR 映射：

- `qwen3_asr`: 拼入 `context`。
- `faster_whisper`、`whisper`、`whisper_cpp`: 拼入 `initial_prompt`。
- `sherpa_onnx_asr`: 首版保留现有 `hotwords_file` 原生能力；二期可把临时热词写入临时文件并注入。
- `fun_asr`: 首版只记录热词命中，不强行注入；二期看具体模型是否支持 hotword 参数。
- 远程 HTTP ASR：按适配器能力决定，不能支持则只做结果对比。

## 音频处理

浏览器端：

- 使用 `navigator.mediaDevices.getUserMedia({ audio: true })`。
- 使用 Web Audio API 收集 PCM。
- 导出 16 kHz mono 16-bit PCM WAV。
- 页面保留录音波形、时长和本地回放。

后端：

- 复用 `/asr` 当前 WAV 解码逻辑，但抽成公共函数，避免重复解析。
- 接收 WAV 后统一转为 `np.float32`，范围 `[-1, 1]`。
- 如果上传采样率不是 16 kHz，首版返回提示；二期再加重采样。

## 准确率指标

中文场景优先使用 CER。

CER：

```text
CER = 编辑距离(识别文本, 参考文本) / 参考文本字符数
```

WER：

- 英文按空格分词。
- 中文首版可选用字符级或简单按空格分词，不作为主要指标。

热词命中：

- 对每个热词做直接包含匹配。
- 支持简繁、大小写归一化可放二期。

## 文件改动计划

新增：

- `docs/asr-benchmark-web-design.md`
- `web_tool/asr_benchmark/index.html`
- `web_tool/asr_benchmark/main.js`
- `web_tool/asr_benchmark/styles.css`
- `src/open_llm_vtuber/asr/benchmark.py`

修改：

- `src/open_llm_vtuber/routes.py`
  - 增加 `/asr-benchmark` 页面重定向。
  - 增加 `/api/asr-benchmark/providers`。
  - 增加 `/api/asr-benchmark/transcribe`。
  - 增加 `/api/asr-benchmark/transcribe/{provider}`。
- `src/open_llm_vtuber/asr/asr_factory.py`
  - 如有必要，补齐按 provider 创建实例时的公共参数过滤。

## 分期

### MVP

- 浏览器录音。
- 上传同一 WAV。
- 并行测试当前已配置的 ASR providers。
- 输出文本、耗时、RTF、热词命中。
- 手填参考文本后前端计算 CER。

### 第二期

- 增加上传历史 WAV 批量测试。
- 生成 CSV/JSON 报告。
- 临时热词自动适配 Sherpa-Onnx hotwords 文件。
- 支持多轮样本统计平均 RTF、平均 CER、P50/P95 延迟。

### 第三期

- 真正流式对比。
- 展示 partial 首字延迟、final 延迟、修正次数。
- 支持展厅噪声分贝、麦克风设备选择和录音环境备注。

## 风险和取舍

- 同时加载多个大模型可能显存不足，所以首版需要按需加载并缓存，不默认加载所有 ASR。
- Qwen3-ASR 属于生成式 ASR，热词是偏置，不是强制词典。
- 浏览器麦克风采样率受设备影响，必须统一导出 16 kHz WAV，否则 RTF 和准确率对比不公平。
- 流式对比先不做，是为了先获得稳定可复现的最终准确率和最终耗时指标。

## 验收标准

- 打开 `/asr-benchmark` 能看到测试页面。
- 页面能录音、回放、上传同一段音频。
- 至少能同时比较当前 `qwen3_asr` 和一个可用备用 ASR。
- 每行显示识别文本、耗时、RTF、热词命中。
- 填入参考文本后能计算 CER。
- 后端错误不会影响其他 ASR 的结果展示。
