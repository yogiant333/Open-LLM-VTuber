# Windows 源码部署：后端 + UE + EdgeTTS

本文档说明如何在另一台 Windows 电脑上从源码部署 Open-LLM-VTuber，只启动后端服务，由 UE 作为前端，TTS 使用微软 EdgeTTS。

这种部署方式不启动 Web 前端，不启动本地 VoxCPM2 TTS，配置要求更低。

## 1. 机器要求

- Windows 10/11
- 可以联网访问 GitHub、Python 包源、LLM API、微软 EdgeTTS 服务
- 已安装 Git
- 已安装 uv
- UE 客户端能连接本机 `ws://127.0.0.1:10002`

安装 uv：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装完成后重新打开 PowerShell，确认：

```powershell
git --version
uv --version
```

## 2. 拉取源码

当前部署只需要使用主仓库分支：

```text
https://github.com/yogiant333/Open-LLM-VTuber/tree/backend-only-windows-deploy
```

不要直接 clone `backend-kws-mic-streaming`。它是前端子模块 `Open-LLM-VTuber-Web` 的分支，主仓库已经通过 `.gitmodules` 指向它。

在客户电脑上执行：

```powershell
cd C:\AI
git clone -b backend-only-windows-deploy https://github.com/yogiant333/Open-LLM-VTuber.git
cd C:\AI\Open-LLM-VTuber
```

如果后续代码已经合并到主分支，可以改用：

```powershell
git clone https://github.com/yogiant333/Open-LLM-VTuber.git
```

## 3. 初始化子模块

后端启动时仍会检查前端子模块是否存在，所以源码部署建议初始化子模块，避免首次启动时自动拉取造成等待。

执行下面命令后，Git 会自动从 `https://github.com/yogiant333/Open-LLM-VTuber-Web` 拉取前端子模块的 `backend-kws-mic-streaming` 分支对应提交；不需要手动 clone 前端仓库。

```powershell
git submodule update --init --recursive
```

## 4. 创建 Python 环境

项目使用 uv 管理 Python 环境。Windows 部署统一使用根目录下的 `.venv`。

```powershell
uv sync
```

确认环境存在：

```powershell
.\.venv\Scripts\python.exe --version
```

## 5. 配置 `.env` 和运行配置

仓库已经包含一份可部署的 `conf.yaml`。不要把真实 API key 写进 `conf.yaml`，默认配置通过环境变量读取密钥。

首次部署时复制 `.env` 示例：

```powershell
Copy-Item .\.env.example .\.env
notepad .\.env
```

填写：

```dotenv
DEEPSEEK_API_KEY=客户自己的 DeepSeek API key
EXA_API_KEY=客户自己的 Exa API key
```

`.env` 已被 `.gitignore` 忽略，不要提交。后端启动时会自动加载项目根目录的 `.env`。

`DEEPSEEK_API_KEY` 用于当前默认 LLM；`EXA_API_KEY` 用于 MCP 搜索服务 `exa-search`。如果客户不使用 MCP 搜索，可以从 `conf.yaml` 的 `mcp_enabled_servers` 中移除 `exa-search`。

如果同时设置了系统环境变量，系统环境变量优先，`.env` 只补充未设置的值。

需要调整运行参数时再编辑：

```powershell
notepad .\conf.yaml
```

至少检查下面几项。

### 后端地址

建议客户机本机部署使用：

```yaml
system_config:
  host: '127.0.0.1'
  port: 18080
```

如果 UE 在另一台电脑上访问这台后端机器，改成：

```yaml
system_config:
  host: '0.0.0.0'
  port: 18080
```

并在 Windows 防火墙放行端口 `18080` 和 `10002`。

### LLM 配置

默认 DeepSeek 配置从环境变量读取 API key：

```yaml
deepseek_llm:
  base_url: 'https://api.deepseek.com'
  llm_api_key: '${DEEPSEEK_API_KEY}'
  model: 'deepseek-v4-flash'
```

不要把真实 API key 写入配置文件或提交到公开仓库。

### EdgeTTS 男声配置

把 TTS 切到 EdgeTTS：

```yaml
tts_config:
  tts_model: 'edge_tts'

  edge_tts:
    voice: zh-CN-YunxiNeural
    proxy: ''
```

`zh-CN-YunxiNeural` 是微软中文男声。如果客户网络直连微软 TTS 超时，再填写代理：

```yaml
proxy: 'http://127.0.0.1:10809'
```

## 6. 测试 EdgeTTS

先单独测试微软 TTS 是否可用：

```powershell
.\.venv\Scripts\python.exe -m edge_tts --voice zh-CN-YunxiNeural --text "你好，我是微软中文男声测试。" --write-media logs\edge-tts-test.mp3
```

如果生成 `logs\edge-tts-test.mp3`，说明 EdgeTTS 可用。

如果失败，通常是网络或代理问题，先检查客户电脑是否能访问微软 TTS 服务。

## 7. 启动后端

只启动后端和 UE WebSocket：

```powershell
.\Start-Windows-Backend-Only.bat
```

启动成功后应看到：

```text
Backend: http://127.0.0.1:18080/
UE WS:   ws://127.0.0.1:10002
```

日志位置：

```text
logs\backend-only-windows.log
logs\backend-only-windows.err.log
```

## 8. UE 连接配置

UE 和后端在同一台电脑：

```text
ws://127.0.0.1:10002
```

UE 在另一台电脑，后端电脑 IP 假设为 `192.168.1.20`：

```text
ws://192.168.1.20:10002
```

这种情况下启动后端时使用：

```powershell
.\Start-Windows-Backend-Only.bat -BindHost 0.0.0.0
```

并放行 Windows 防火墙端口：

- `18080`
- `10002`

## 9. 停止和重启

重新运行：

```powershell
.\Start-Windows-Backend-Only.bat
```

脚本会自动停止旧的后端进程和旧的 UE WebSocket 监听，再启动新服务。

## 10. 更新代码

进入项目目录：

```powershell
cd C:\AI\Open-LLM-VTuber
git pull
git submodule update --init --recursive
uv sync
```

如果更新后依赖变化，重新运行 `uv sync`。

## 11. 常见问题

### 找不到 `.venv\Scripts\python.exe`

说明没有执行过依赖安装：

```powershell
uv sync
```

### EdgeTTS 没声音或生成失败

先运行测试命令：

```powershell
.\.venv\Scripts\python.exe -m edge_tts --voice zh-CN-YunxiNeural --text "测试。" --write-media logs\edge-tts-test.mp3
```

如果失败，检查网络或给 `edge_tts.proxy` 配代理。

### UE 连不上

检查端口：

```powershell
netstat -ano | findstr /C:":10002" /C:":18080"
```

本机部署应看到 `127.0.0.1:10002` 和 `127.0.0.1:18080` 在监听。

跨电脑访问时确认：

- 后端用 `-BindHost 0.0.0.0` 启动
- UE 填的是后端电脑的局域网 IP
- Windows 防火墙已放行 `10002` 和 `18080`

### 不需要 VoxCPM2 吗？

EdgeTTS 部署不需要 VoxCPM2，也不需要 `50005` 本地 TTS 服务。只有需要本地声音克隆、离线 TTS 或指定音色效果时，才切回 VoxCPM2。
