# 本地部署与运行说明

本文档记录当前本机 Open-LLM-VTuber 的实际运行方式。

## 当前代码目录

唯一代码目录使用 Windows 路径：

```text
C:\AI\Open-LLM-VTuber
```

WSL 中访问同一份代码时使用：

```bash
/mnt/c/AI/Open-LLM-VTuber
```

不要再把 `/home/yy/AI/Open-LLM-VTuber` 当作运行代码目录，否则 Windows 和 WSL 会变成两份代码，容易出现改了 Windows 文件但服务仍在跑旧代码的问题。

## 当前运行环境

- 代码：`/mnt/c/AI/Open-LLM-VTuber`
- Python 环境：WSL conda 环境 `open-llm-vtuber-py312`
- 后端：`http://127.0.0.1:18080/`
- Web 前端：`http://127.0.0.1:3000/`
- UE WebSocket：`ws://127.0.0.1:10002`
- 后端 tmux：`open-llm-vtuber`
- 前端 tmux：`open-llm-vtuber-frontend`

## 启动服务

在 PowerShell 中启动：

```powershell
wsl.exe -d Ubuntu -- bash -lc "cd /mnt/c/AI/Open-LLM-VTuber && ./start_wsl.sh"
```

在 WSL 终端中启动：

```bash
cd /mnt/c/AI/Open-LLM-VTuber
./start_wsl.sh
```

`start_wsl.sh` 会：

1. 加载项目根目录 `.env`。
2. 激活 WSL conda 环境 `open-llm-vtuber-py312`。
3. 用 tmux 启动后端 `python run_server.py`。
4. 用 tmux 启动前端 `npm run dev:web -- --host 127.0.0.1 --force`。
5. 等待 `18080` 和 `3000` ready。

## 停止服务

```bash
tmux kill-session -t open-llm-vtuber
tmux kill-session -t open-llm-vtuber-frontend
```

如果需要清理残留 ASR vLLM 进程：

```bash
pkill -f "VLLM::EngineCore|run_server.py"
```

## 查看日志

后端日志：

```bash
tmux attach -t open-llm-vtuber
```

前端日志：

```bash
tmux attach -t open-llm-vtuber-frontend
```

从 PowerShell 直接查看后端最近日志：

```powershell
wsl.exe -d Ubuntu -- bash -lc "tmux capture-pane -t open-llm-vtuber -p -S -200 | tail -120"
```

Windows VoxCPM2 TTS 日志：

```text
C:\AI\Open-LLM-VTuber\logs\voxcpm2-windows.log
C:\AI\Open-LLM-VTuber\logs\voxcpm2-windows.err.log
```

## 环境变量

真实密钥放在项目根目录 `.env`，不要提交：

```text
C:\AI\Open-LLM-VTuber\.env
```

至少需要：

```dotenv
DEEPSEEK_API_KEY=...
EXA_API_KEY=...
```

`conf.yaml` 通过 `${DEEPSEEK_API_KEY}`、`${EXA_API_KEY}` 引用这些变量。后端如果没有从 `.env` 读取到 key，LLM/MCP 会出现异常行为。

## 当前语音链路

ASR 当前使用 Qwen3-ASR vLLM：

```yaml
asr_model: 'qwen3_asr'
qwen3_asr:
  backend: 'vllm'
  model_name: 'Qwen/Qwen3-ASR-0.6B'
  vllm_gpu_memory_utilization: 0.25
  vllm_max_model_len: 1024
```

TTS 当前使用 Windows VoxCPM2 NanoVLLM HTTP 服务：

```yaml
tts_model: 'voxcpm2_tts'
voxcpm2_tts:
  base_url: 'http://172.25.112.1:50005'
```

Windows 侧健康检查：

```powershell
curl.exe --noproxy "*" http://127.0.0.1:50005/health
```

WSL 侧健康检查需要使用 Windows WSL 网关地址，当前示例：

```bash
curl http://172.25.112.1:50005/health
```

如果 WSL 网关变化，用下面命令查看：

```bash
ip route | awk '/default/ {print $3; exit}'
```

## 验证

启动后检查：

```powershell
curl.exe --noproxy "*" -I http://127.0.0.1:18080/
curl.exe --noproxy "*" -I http://127.0.0.1:3000/
```

确认 WSL 实际跑的是 Windows 目录代码：

```powershell
wsl.exe -d Ubuntu -- ps -eo pid,args
```

正常应能看到类似：

```text
cd '/mnt/c/AI/Open-LLM-VTuber' && python run_server.py
node /mnt/c/AI/Open-LLM-VTuber/frontend/...
```
