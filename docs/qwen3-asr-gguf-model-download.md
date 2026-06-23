# Qwen3-ASR-GGUF 模型下载

当前 Windows 部署默认使用 `qwen3_asr_gguf`，代码子模块在 `Qwen3-ASR-GGUF`，模型和 Windows runtime DLL 都是本地部署资产，不提交到 git。

## 一键下载

在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe .\scripts\download_deploy_models.py
```

脚本会下载并放置：

- `Qwen3-ASR-GGUF\model\qwen3_asr_encoder_frontend.fp16.onnx`
- `Qwen3-ASR-GGUF\model\qwen3_asr_encoder_backend.fp16.onnx`
- `Qwen3-ASR-GGUF\model\qwen3_asr_llm.q5_k.gguf`
- `Qwen3-ASR-GGUF\model\qwen3_aligner_encoder_frontend.int4.onnx`
- `Qwen3-ASR-GGUF\model\qwen3_aligner_encoder_backend.int4.onnx`
- `Qwen3-ASR-GGUF\model\qwen3_aligner_llm.q4_k.gguf`
- `Qwen3-ASR-GGUF\qwen_asr_gguf\inference\bin\llama.dll` 等 Windows runtime DLL

下载缓存默认保存在 `downloads\deploy-models`，该目录被 git 忽略。

## 来源

- ASR 1.7B fp16/q5_k：`HaujetZhao/CapsWriter-Offline` 的 `Qwen3-ASR-1.7B-q5_k.zip`
- Aligner 0.6B int4/q4_k：`HaujetZhao/Qwen3-ASR-GGUF` 的 `Qwen3-ForceAligner-0.6B-gguf.zip`
- Windows runtime：`HaujetZhao/Qwen3-ASR-GGUF` 的 `Qwen3-ASR-Transcribe-20260223.zip`

## 验证

下载后运行：

```powershell
.\.venv\Scripts\python.exe .\scripts\bench_qwen3_asr_gguf_windows.py --audio .\doc\黑神话\1.mp3 --srt .\doc\黑神话\1.srt --max-segments 3
```

或者直接启动后端：

```powershell
.\Start-Windows-Backend-Only.ps1
```

后端启动脚本会检查 DirectML、子模块、模型文件和 `llama.dll` 是否存在。
