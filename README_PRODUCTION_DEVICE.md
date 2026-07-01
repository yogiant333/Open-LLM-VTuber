# 生产设备打包与部署文档

本文档说明如何把当前项目打包成 Windows 生产设备部署包，并在生产设备上一键启动新前端、Open-LLM-VTuber 后端、LiveTalking 和 VoxCPM2 TTS。

## 1. 部署形态

生产设备采用 Windows 原生多服务部署，不使用 Docker，不做 PyInstaller 单文件化。

服务端口固定如下：

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 新前端 | `http://127.0.0.1:3000/` | 用户唯一入口 |
| Open-LLM-VTuber 后端 | `http://127.0.0.1:18080/` | 对话、ASR、LLM、TTS 调度 |
| Open-LLM-VTuber WebSocket | `ws://127.0.0.1:18080/client-ws` | 新前端连接后端 |
| LiveTalking | `http://127.0.0.1:18010/` | WebRTC 数字人视频和口型 |
| VoxCPM2 TTS | `http://127.0.0.1:50005/health` | 低延迟 TTS 服务 |

新前端只暴露一个入口，内部代理：

```text
/client-ws      -> http://127.0.0.1:18080/client-ws
/livetalking/*  -> http://127.0.0.1:18010/*
```

浏览器只需要打开：

```text
http://127.0.0.1:3000/
```

## 2. 打包前检查

在开发机确认这些目录和文件存在：

```text
E:\AI\Open-LLM-VTuber
E:\AI\LiveTalking
C:\AI\voxcpm2-nanovllm-win-venv
```

其中 `C:\AI\voxcpm2-nanovllm-win-venv` 如果不存在，打包脚本会自动跳过 TTS。生产设备上需要单独放好 TTS 目录，否则启动会失败。

开发机需要能运行：

```bat
npm run build
```

打包脚本会在 `livetalking-showcase` 下构建新前端。

## 3. 一键打包

在项目根目录双击或运行：

```bat
package_production_device.bat
```

该 bat 不需要传参，默认使用：

```text
LiveTalking: E:\AI\LiveTalking
TTS: C:\AI\voxcpm2-nanovllm-win-venv
```

输出目录：

```text
deployment_packages\Open-LLM-VTuber-production-YYYYMMDD-HHMMSS\
deployment_packages\Open-LLM-VTuber-production-YYYYMMDD-HHMMSS.zip
```

打包完成后，窗口会停在 `Packaging completed.`，方便确认结果。

## 4. 高级打包方式

普通现场交付用 bat 即可。只有需要改路径或跳过大文件时，才直接调用 PowerShell 脚本。

示例：指定 LiveTalking 和 TTS 路径：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_production_device.ps1 `
  -LiveTalkingDir E:\AI\LiveTalking `
  -TtsDir C:\AI\voxcpm2-nanovllm-win-venv
```

只生成代码包，不复制主项目模型目录：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_production_device.ps1 -SkipModels
```

跳过 TTS：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_production_device.ps1 -SkipTts
```

跳过 LiveTalking `.venv`：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_production_device.ps1 -SkipLiveTalkingVenv
```

只生成目录，不压缩 zip：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_production_device.ps1 -NoArchive
```

## 5. 部署到生产设备

推荐把 zip 解压到：

```text
C:\AI
```

解压后目录结构应类似：

```text
C:\AI
  Open-LLM-VTuber\
  frontend-runtime\
    dist\
    server.js
  LiveTalking\
  voxcpm2-nanovllm-win-venv\
  start_all.bat
  start_all.ps1
  stop_all.bat
  stop_all.ps1
  healthcheck.bat
  healthcheck.ps1
  package-manifest.json
  README_PRODUCTION_DEVICE.md
```

如果打包时跳过了 TTS，需要手动确保生产设备存在：

```text
C:\AI\voxcpm2-nanovllm-win-venv
```

如果打包时跳过了模型，需要手动补齐：

```text
C:\AI\Open-LLM-VTuber\Qwen3-ASR-GGUF\model
C:\AI\Open-LLM-VTuber\models
```

## 6. 启动

在生产设备双击：

```bat
C:\AI\start_all.bat
```

启动顺序为：

1. LiveTalking，监听 `18010`
2. VoxCPM2 TTS，监听 `50005`
3. Open-LLM-VTuber 后端，监听 `18080`
4. 新前端运行器，监听 `3000`

启动成功后打开：

```text
http://127.0.0.1:3000/
```

## 7. 健康检查

双击：

```bat
C:\AI\healthcheck.bat
```

健康检查会确认：

```text
http://127.0.0.1:3000/health
http://127.0.0.1:18080/
http://127.0.0.1:50005/health
http://127.0.0.1:18010/api/admin/sessions
```

全部通过时会显示：

```text
All health checks passed.
```

## 8. 停止

双击：

```bat
C:\AI\stop_all.bat
```

该脚本会停止监听以下端口的进程：

```text
3000, 18010, 18080, 10002, 50005
```

## 9. 日志位置

Open-LLM-VTuber 后端日志：

```text
C:\AI\Open-LLM-VTuber\logs\backend-only-windows.log
C:\AI\Open-LLM-VTuber\logs\backend-only-windows.err.log
```

VoxCPM2 TTS 日志：

```text
C:\AI\Open-LLM-VTuber\logs\voxcpm2-windows.log
C:\AI\Open-LLM-VTuber\logs\voxcpm2-windows.err.log
```

新前端运行器日志：

```text
C:\AI\logs\frontend-runtime.log
C:\AI\logs\frontend-runtime.err.log
```

LiveTalking 日志：

```text
C:\AI\LiveTalking\.omx\logs\
```

如果 LiveTalking 没有使用自带 `scripts\start_xiaomeng.ps1`，日志会写到：

```text
C:\AI\logs\livetalking.out.log
C:\AI\logs\livetalking.err.log
```

## 10. 配置注意事项

生产设备需要保留真实本地配置：

```text
C:\AI\Open-LLM-VTuber\conf.yaml
C:\AI\Open-LLM-VTuber\.env
```

`conf.yaml` 中 TTS 地址应为：

```text
http://127.0.0.1:50005
```

DeepSeek V4 语音对话建议保持：

```yaml
thinking: disabled
```

声音克隆 prompt WAV 和私有模型文件只放本地，不要提交到仓库。

## 11. 常见问题

### 打包时提示 TTS 目录不存在

`package_production_device.bat` 会自动跳过 TTS。这不是打包失败，但生产设备启动前必须补齐：

```text
C:\AI\voxcpm2-nanovllm-win-venv
```

### 启动后前端打不开

先运行：

```bat
C:\AI\healthcheck.bat
```

再看：

```text
C:\AI\logs\frontend-runtime.err.log
```

常见原因是生产设备没有安装 Node.js，或 `3000` 端口被占用。

### LiveTalking 失败

检查：

```text
C:\AI\LiveTalking\scripts\start_xiaomeng.ps1
C:\AI\LiveTalking\data\avatars\xiaomeng_wav2lip256
C:\AI\LiveTalking\models\wav2lip.pth
```

再看：

```text
C:\AI\LiveTalking\.omx\logs\
```

### 后端启动失败

检查：

```text
C:\AI\Open-LLM-VTuber\.venv\Scripts\python.exe
C:\AI\Open-LLM-VTuber\Qwen3-ASR-GGUF\model
C:\AI\Open-LLM-VTuber\conf.yaml
C:\AI\Open-LLM-VTuber\.env
```

再看：

```text
C:\AI\Open-LLM-VTuber\logs\backend-only-windows.err.log
```

### WebSocket 或 LiveTalking 跨域问题

生产环境不要直接打开 LiveTalking 页面，也不要让新前端直连多个跨域地址。只打开：

```text
http://127.0.0.1:3000/
```

新前端运行器会统一代理 `/client-ws` 和 `/livetalking`。

## 12. 不推荐方案

不建议把本项目做成 PyInstaller 单文件。当前链路包含 DirectML、ONNX Runtime、llama.cpp DLL、WebRTC、Node 前端、LiveTalking、VoxCPM2 和大量模型文件，单文件化会显著增加排障成本。

不建议优先 Docker。当前 ASR/TTS/LiveTalking 都按 Windows 原生 GPU 路径调通，生产设备用 Windows 原生服务更稳定。
