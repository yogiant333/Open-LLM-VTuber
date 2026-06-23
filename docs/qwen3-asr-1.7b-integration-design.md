# Qwen3-ASR 1.7B 接入分析与设计

## 背景

目标是在 Open-LLM-VTuber 中新增 `Qwen/Qwen3-ASR-1.7B` 作为可选 ASR 引擎，用于替换或补充当前的 `sherpa_onnx_asr`。第一阶段优先保证现有后端、UE 前端、KWS、VAD 和会话逻辑不变，只把“整段语音转文字”这一层替换为 Qwen3-ASR。

当前实施决策：第一阶段必须使用 GPU，不允许 CPU 回退；先采用进程内 transformers 后端，不使用独立 HTTP 服务。

官方资料显示，Qwen3-ASR 系列支持离线和流式推理，覆盖 30 种语言和 22 种中文方言，模型权重和代码以 Apache-2.0 发布。官方 `qwen-asr` 包支持 transformers 后端和 vLLM 后端，其中流式推理当前只支持 vLLM 后端。

参考资料：

- Hugging Face model card: https://huggingface.co/Qwen/Qwen3-ASR-1.7B
- Qwen3-ASR GitHub: https://github.com/QwenLM/Qwen3-ASR
- vLLM Qwen3-ASR serving: https://docs.vllm.ai/

## 当前 ASR 链路

当前项目已经有清晰的 ASR 抽象：

- `src/open_llm_vtuber/asr/asr_interface.py`
  - 定义 `ASRInterface`
  - 标准输入是 `np.ndarray`
  - 默认采样率是 `16000`
  - 核心方法是 `async_transcribe_np(audio)` / `transcribe_np(audio)`
- `src/open_llm_vtuber/asr/asr_factory.py`
  - 根据 `asr_config.asr_model` 创建具体 ASR 实例
- `src/open_llm_vtuber/config_manager/asr.py`
  - 使用 Pydantic 定义 ASR 配置结构和合法 provider
- `src/open_llm_vtuber/service_context.py`
  - `ServiceContext.init_asr()` 读取配置并初始化 ASR
- `src/open_llm_vtuber/conversations/conversation_utils.py`
  - 对话链路里调用 `asr_engine.async_transcribe_np(user_input)`
- `src/open_llm_vtuber/routes.py`
  - `/asr` 接口也复用同一个 ASR 引擎

因此接入点不需要改动对话主流程，只需要新增一个 ASR provider，并让配置可以选择它。

## Qwen3-ASR 能力与约束

### 能力

- 模型：`Qwen/Qwen3-ASR-1.7B`
- 输入：官方 `qwen-asr` 支持本地路径、URL、base64、`(np.ndarray, sr)` tuple
- 输出：识别语言和文本
- 推理模式：
  - transformers：适合第一阶段离线整句识别
  - vLLM：适合高吞吐、服务化、流式识别
- 可选时间戳：
  - 需要额外加载 `Qwen/Qwen3-ForcedAligner-0.6B`
  - 本项目第一阶段不需要时间戳

### 约束

- 官方建议使用干净的 Python 3.12 环境安装 `qwen-asr`。
- 当前项目已提升为 Python `>=3.12,<3.13`，Windows 后端应使用 Python 3.12 `.venv`。
- Windows 默认 PyPI 安装到的 PyTorch 可能不是 CUDA 版，必须通过 PyTorch CUDA wheel 源安装或重装 torch。
- `Qwen3-ASR-1.7B` 不允许在本项目中 CPU 回退。没有 CUDA GPU 时应启动失败并给出明确错误。
- 第一阶段现有链路是“VAD 收集完整语音段后再 ASR”，不是逐 chunk 流式 ASR。要做真正流式，需要改 websocket 音频处理状态机。

## 推荐方案

### 第一阶段：进程内 transformers 离线整句接入

新增 provider：`qwen3_asr`

特点：

- 改动最小
- 保持现有 KWS/VAD/对话链路不变
- 输入直接使用当前 `np.ndarray` 音频
- 适合验证识别效果、配置切换和 UE 演示链路
- 必须使用 `cuda...` 设备，配置和运行时都禁止 CPU

新增文件：

- `src/open_llm_vtuber/asr/qwen3_asr.py`

修改文件：

- `src/open_llm_vtuber/asr/asr_factory.py`
- `src/open_llm_vtuber/config_manager/asr.py`
- `conf.yaml`
- `pyproject.toml` 或独立安装说明

建议配置：

```yaml
character_config:
  asr_config:
    asr_model: 'qwen3_asr'
    qwen3_asr:
      model_name: 'Qwen/Qwen3-ASR-1.7B'
      device_map: 'cuda:0'
      dtype: 'bfloat16'
      language: 'Chinese'
      max_new_tokens: 256
      max_inference_batch_size: 1
      attn_implementation: null
```

字段说明：

- `model_name`：模型名或本地模型目录。客户电脑建议提前下载到本地目录。
- `device_map`：默认 `cuda:0`。没有 GPU 时可设为 `cpu`，但不建议用于低延迟演示。
- `dtype`：推荐 `bfloat16`，兼容性不足时回退 `float16` 或 `float32`。
- `language`：展厅中文场景建议固定 `Chinese`，减少自动语种判断的不确定性。
- `max_new_tokens`：短问答场景 256 足够，长音频再调大。
- `max_inference_batch_size`：本项目单路语音优先设为 1，避免额外显存压力。
- `attn_implementation`：有 FlashAttention 2 环境时可设 `flash_attention_2`。

### 第二阶段：独立 Qwen3-ASR 服务

这是后续备选，不作为第一阶段实现。它会增加一次本机 HTTP 调用、音频编码/解码和序列化开销；优势是依赖隔离、独立升级和独立重启。如果进程内加载导致后端启动慢、依赖冲突或显存管理困难，再考虑把 Qwen3-ASR 独立成服务：

- Open-LLM-VTuber 主后端仍使用现有 Python 环境。
- Qwen3-ASR 使用单独 conda 环境或 Docker。
- 主后端新增 provider：`qwen3_asr_http`
- ASR 调用通过 HTTP 发送 WAV/base64，返回文本。

推荐服务接口：

```http
GET /health
POST /v1/asr
```

请求：

```json
{
  "audio_base64": "...",
  "sample_rate": 16000,
  "language": "Chinese"
}
```

响应：

```json
{
  "text": "识别出的文字",
  "language": "Chinese",
  "elapsed_ms": 820
}
```

这个方案更适合客户电脑部署，因为主项目依赖不会被 `qwen-asr` / `vLLM` 影响，升级时也可以单独升级 ASR 服务。

### 第三阶段：vLLM 流式或 OpenAI-compatible 服务

当需要进一步降低首字延迟时，再考虑 vLLM：

- 启动方式可用官方 `qwen-asr-serve Qwen/Qwen3-ASR-1.7B --host 0.0.0.0 --port 8000`
- 或直接 `vllm serve Qwen/Qwen3-ASR-1.7B`
- 主后端以 OpenAI-compatible 音频消息或专用 HTTP adapter 调用

注意：这不是第一阶段最佳路径。当前项目的音频入口是 VAD 完整切段后转写，即使 ASR 后端支持流式，如果不改 websocket 音频状态机，也无法获得真正的流式交互收益。

## 代码设计

### `Qwen3ASRConfig`

在 `src/open_llm_vtuber/config_manager/asr.py` 新增：

```python
class Qwen3ASRConfig(I18nMixin):
    model_name: str = Field("Qwen/Qwen3-ASR-1.7B", alias="model_name")
    device_map: str = Field("cuda:0", alias="device_map")
    dtype: Literal["bfloat16", "float16"] = Field("bfloat16", alias="dtype")
    language: Optional[str] = Field("Chinese", alias="language")
    max_new_tokens: int = Field(256, alias="max_new_tokens")
    max_inference_batch_size: int = Field(1, alias="max_inference_batch_size")
    attn_implementation: Optional[str] = Field(None, alias="attn_implementation")
```

同时把 `ASRConfig.asr_model` 的 Literal 增加 `"qwen3_asr"`，并增加：

```python
qwen3_asr: Optional[Qwen3ASRConfig] = Field(None, alias="qwen3_asr")
```

### `ASRFactory`

在 `src/open_llm_vtuber/asr/asr_factory.py` 增加：

```python
elif system_name == "qwen3_asr":
    from .qwen3_asr import VoiceRecognition as Qwen3ASR
    return Qwen3ASR(**kwargs)
```

### `qwen3_asr.py`

核心行为：

- 延迟到初始化时加载 `qwen_asr.Qwen3ASRModel`
- 初始化时检查 `torch.cuda.is_available()`，没有 CUDA 直接失败
- `device_map` 必须以 `cuda` 开头，禁止 `cpu` 和自动 CPU 回退
- 把当前输入的 `np.ndarray` 转为 `float32`
- 调用 `model.transcribe(audio=(audio, self.SAMPLE_RATE), language=self.language)`
- 返回 `results[0].text.strip()`
- 捕获缺依赖错误，给出明确安装提示

伪代码：

```python
class VoiceRecognition(ASRInterface):
    def __init__(...):
        import torch
        from qwen_asr import Qwen3ASRModel

        dtype_map = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }

        kwargs = {
            "dtype": dtype_map[dtype],
            "device_map": device_map,
            "max_inference_batch_size": max_inference_batch_size,
            "max_new_tokens": max_new_tokens,
        }
        if attn_implementation:
            kwargs["attn_implementation"] = attn_implementation

        self.model = Qwen3ASRModel.from_pretrained(model_name, **kwargs)
        self.language = language

    def transcribe_np(self, audio: np.ndarray) -> str:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        results = self.model.transcribe(
            audio=(audio, self.SAMPLE_RATE),
            language=self.language,
        )
        return results[0].text.strip()
```

## 依赖与部署

### 进程内方案

Windows 推荐直接运行项目内安装脚本：

```powershell
.\scripts\setup_windows_qwen3_asr_gpu.ps1
```

脚本会：

- 检查并创建 Python 3.12 `.venv`
- 如果现有 `.venv` 不是 Python 3.12，会安全删除后重建
- 安装项目依赖和 `qwen-asr`
- 从 PyTorch CUDA wheel 源重装 CUDA 版 `torch` / `torchaudio`
- 验证 `qwen_asr` 可导入、`torch.cuda.is_available()` 为 true

手动安装等价流程：

```powershell
uv venv --python 3.12 .venv
uv pip install --python .\.venv\Scripts\python.exe -e .
uv pip install --python .\.venv\Scripts\python.exe --reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu129
```

如果使用 vLLM：

```powershell
pip install -U "qwen-asr[vllm]"
```

模型建议提前下载：

```powershell
pip install -U modelscope
modelscope download --model Qwen/Qwen3-ASR-1.7B --local_dir C:\AI\models\Qwen3-ASR-1.7B
```

然后配置：

```yaml
model_name: 'C:\AI\models\Qwen3-ASR-1.7B'
```

### 服务化方案

建议目录：

```text
C:\AI\qwen3-asr-service
C:\AI\models\Qwen3-ASR-1.7B
```

建议启动脚本：

```powershell
conda activate qwen3-asr
python server.py --model C:\AI\models\Qwen3-ASR-1.7B --host 127.0.0.1 --port 18090
```

主项目配置：

```yaml
asr_model: 'qwen3_asr_http'
qwen3_asr_http:
  base_url: 'http://127.0.0.1:18090'
  language: 'Chinese'
  timeout: 60
```

## 性能风险

- 首次启动会加载 1.7B 模型，启动时间会明显增加。
- GPU 显存不足时会 OOM。1.7B + bfloat16 + transformers 通常需要独占一部分显存，不能和大 LLM/TTS 模型无规划共用。
- 如果同机还运行数字人、LLM、VoxCPM2 TTS，建议先用独立服务，便于分别控制 GPU 和重启。
- 低配客户电脑建议保留 `sherpa_onnx_asr` 或 `edge_tts` 级别的低配置方案，Qwen3-ASR 作为高配选项。

## 当前实测运行方案

截至 2026-06-17，本机推荐运行方式已经从 Windows 原生后端切换为 WSL2 + conda + vLLM，并统一使用 Windows 目录中的同一份代码：

```text
Windows 代码目录: C:\AI\Open-LLM-VTuber
WSL 代码目录: /mnt/c/AI/Open-LLM-VTuber
conda 环境: open-llm-vtuber-py312
启动脚本: ./start_wsl.sh
后端地址: http://127.0.0.1:18080/
UE WebSocket: ws://127.0.0.1:10002
Web 前端: http://127.0.0.1:3000/
```

不要再从 `/home/yy/AI/Open-LLM-VTuber` 启动服务；该路径会形成第二份代码，导致 Windows 侧修改无法立即反映到运行服务。

Windows 原生后端不要同时启动，否则会与 WSL 后端争用 `18080` 和 `10002`。启动前应确认：

```powershell
Get-NetTCPConnection -LocalPort 18080,10002,3000 -State Listen
```

当前正常状态下，端口所有者应为 WSL relay，而不是 Windows `python.exe`。

### 当前 ASR 配置

`conf.yaml` 当前使用进程内 vLLM 后端，而不是 transformers：

```yaml
character_config:
  asr_config:
    asr_model: 'qwen3_asr'
    qwen3_asr:
      backend: 'vllm'
      model_name: 'Qwen/Qwen3-ASR-0.6B'
      device_map: 'cuda:0'
      dtype: 'bfloat16'
      language: 'Chinese'
      max_new_tokens: 128
      max_inference_batch_size: 1
      vllm_gpu_memory_utilization: 0.25
      vllm_tensor_parallel_size: 1
      vllm_max_model_len: 1024
      vllm_enforce_eager: false
```

这组配置的目标是让 Qwen3-ASR 与 Windows VoxCPM2 TTS 同时常驻。`vllm_max_model_len=1024` 会限制超长输入和并发能力，但对当前展厅数字人短问答足够。

### 当前实测性能

当前常驻组合为 Windows VoxCPM2 TTS + WSL Qwen3-ASR 0.6B vLLM。

```text
Windows VoxCPM2 TTS 单独运行: 约 16.1GB
TTS + Qwen3-ASR 0.6B + 后端运行: 约 19.1GB
剩余显存: 约 5.0GB
Qwen3-ASR 0.6B 模型权重加载日志: 1.53 GiB
Qwen3-ASR 0.6B KV cache 可用日志: 0.83 GiB
GPU KV cache size: 7,744 tokens
```

5.5 秒短音频 RTF 实测：

```text
第一次识别 RTF: 2.3052
第二次识别 RTF: 0.0272
第三次识别 RTF: 0.0273
```

第一条请求会包含 vLLM warm-up/编译开销，不能代表常驻服务速度。评估速度时应至少跑两次同一段音频，取第二次及之后的结果。

### 启停命令

启动 WSL 版服务：

```bash
cd /mnt/c/AI/Open-LLM-VTuber
./start_wsl.sh
```

查看日志：

```bash
tmux attach -t open-llm-vtuber
tmux attach -t open-llm-vtuber-frontend
```

停止 WSL 版服务：

```bash
tmux kill-session -t open-llm-vtuber
tmux kill-session -t open-llm-vtuber-frontend
```

如果必须进一步降低显存，优先继续优化 0.6B 的常驻参数；继续压低 1.7B 的 vLLM cache 会牺牲长音频能力和并发余量，且和 Windows VoxCPM2 同时常驻时显存压力更大。

## 验证方案

### 单元级验证

- `python -m py_compile src/open_llm_vtuber/asr/qwen3_asr.py`
- `python -m py_compile src/open_llm_vtuber/config_manager/asr.py`
- `python -m py_compile src/open_llm_vtuber/asr/asr_factory.py`

### 配置验证

- 使用 `conf.yaml` 切到 `qwen3_asr`
- 启动后确认日志出现：
  - `Initializing ASR: qwen3_asr`
  - `Qwen3-ASR model loaded`
- 缺依赖时应输出明确错误，而不是泛化 ImportError。

### 接口验证

- 调用 `/asr` 上传一段 16k 单声道 WAV
- 预期返回中文文本
- 验证空音频、噪声、过短音频不会导致后端崩溃

### 端到端验证

- KWS 开启
- 说“小智小智”后提问
- 日志确认链路为：
  - KWS 命中
  - VAD 收音结束
  - Qwen3-ASR 输出文本
  - LLM 生成回复
  - TTS 播放

## 实施顺序

1. 新增 `Qwen3ASRConfig` 和配置 schema。
2. 新增 `qwen3_asr.py` provider。
3. 在 `ASRFactory` 注册 `qwen3_asr`。
4. 在 `conf.yaml` 增加示例配置，但不默认切换，先保留当前 `sherpa_onnx_asr`。
5. 在部署文档增加模型下载和依赖安装说明。
6. 本机安装 `qwen-asr` 后做 `/asr` 接口验证。
7. 如果依赖冲突或启动耗时不可接受，再改为 `qwen3_asr_http` 服务化方案。

## 建议结论

第一版已按 `qwen3_asr` 进程内 GPU-only 离线整句接入推进，用来快速验证识别质量并避免 HTTP 通讯开销。若后续目标转为客户电脑批量稳定部署，再评估独立 `qwen3_asr_http` 服务，因为它能隔离重依赖、降低主后端启动风险，也更方便单独升级模型和服务。
