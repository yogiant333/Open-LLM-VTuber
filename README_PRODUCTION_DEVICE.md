# 生产设备打包与部署

本项目的生产形态是 Windows 原生多服务部署：

- 新前端：`http://127.0.0.1:3000/`
- Open-LLM-VTuber 后端：`http://127.0.0.1:18080/`
- LiveTalking：`http://127.0.0.1:18010/`
- VoxCPM2 TTS：`http://127.0.0.1:50005/health`

浏览器只需要打开新前端。新前端运行器会代理：

- `/client-ws` -> Open-LLM-VTuber `/client-ws`
- `/livetalking/*` -> LiveTalking

## 在开发机打包

从项目根目录运行：

```bat
package_production_device.bat
```

该 bat 默认使用：

```text
LiveTalking: E:\AI\LiveTalking
TTS: C:\AI\voxcpm2-nanovllm-win-venv
```

如果 TTS 目录不存在，bat 会自动跳过 TTS 打包，并提示后续在生产设备上单独放好 TTS。

等价 PowerShell 命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_production_device.ps1 `
  -LiveTalkingDir E:\AI\LiveTalking `
  -TtsDir C:\AI\voxcpm2-nanovllm-win-venv
```

如果 TTS 目录不在本机，或者准备在目标设备上单独安装 TTS，可以加：

```powershell
-SkipTts
```

如果只想先生成代码包，不复制主项目里的模型目录，可以加：

```powershell
-SkipModels
```

如果 LiveTalking 的 `.venv` 太大，并且目标设备会单独创建 LiveTalking Python 环境，可以加：

```powershell
-SkipLiveTalkingVenv
```

输出位置默认是：

```text
deployment_packages\Open-LLM-VTuber-production-YYYYMMDD-HHMMSS\
deployment_packages\Open-LLM-VTuber-production-YYYYMMDD-HHMMSS.zip
```

## 复制到生产设备

推荐把压缩包解压到：

```text
C:\AI
```

解压后应看到：

```text
C:\AI\Open-LLM-VTuber
C:\AI\frontend-runtime
C:\AI\LiveTalking
C:\AI\voxcpm2-nanovllm-win-venv
C:\AI\start_all.ps1
C:\AI\start_all.bat
C:\AI\stop_all.ps1
C:\AI\stop_all.bat
C:\AI\healthcheck.ps1
C:\AI\healthcheck.bat
```

## 启动

```powershell
C:\AI\start_all.bat
```

启动成功后打开：

```text
http://127.0.0.1:3000/
```

## 健康检查

```powershell
C:\AI\healthcheck.bat
```

## 停止

```powershell
C:\AI\stop_all.bat
```

## 常见调整

如果 LiveTalking Python 不在包内 `.venv`，启动时显式传入：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\AI\start_all.ps1 `
  -LiveTalkingPython C:\tools\miniconda3\envs\livetalking\python.exe
```

如果端口被现场系统占用，优先改启动参数，前端仍作为唯一入口：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\AI\start_all.ps1 `
  -FrontendPort 3000 `
  -LiveTalkingPort 18010 `
  -BackendPort 18080 `
  -TtsPort 50005
```

## 注意

- `.env` 和 `conf.yaml` 会被打进部署包，因为生产设备需要真实本地配置。
- 私有 prompt WAV、模型文件和 avatar 素材体积很大，复制前确认授权和磁盘空间。
- 不建议用 PyInstaller 单文件化这套链路；DirectML、WebRTC、ONNX、llama.cpp DLL 和模型文件会让单文件包更难维护。
