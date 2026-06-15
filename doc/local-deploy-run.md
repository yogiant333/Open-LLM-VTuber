# 本地部署与运行说明

本文档记录当前这份本地 Open-LLM-VTuber 项目的部署和运行方式。

## 当前路径

项目目录：

```text
/mnt/d/AI/Open-LLM-VTuber
```

Windows 对应目录通常是：

```text
D:\AI\Open-LLM-VTuber
```

主配置文件：

```text
/mnt/d/AI/Open-LLM-VTuber/conf.yaml
```

## 双击运行

在 Windows 文件管理器中双击根目录脚本：

```text
start_open_llm_vtuber.bat
```

脚本会执行：

1. 检查 `http://localhost:12393` 是否已经运行。
2. 如果已经运行，直接打开浏览器。
3. 如果没有运行，通过 WSL 进入项目目录。
4. 执行 `uv run run_server.py` 启动服务。
5. 延迟打开浏览器访问 `http://localhost:12393`。

使用时保持脚本窗口打开。关闭窗口会停止服务。

## 手动运行

如果不用双击脚本，可以在 WSL 终端执行：

```bash
cd /mnt/d/AI/Open-LLM-VTuber
uv run run_server.py
```

然后浏览器打开：

```text
http://localhost:12393
```

## 首次部署步骤

当前环境已经完成过部署。重新部署时可以按下面步骤执行：

```bash
cd /mnt/d/AI/Open-LLM-VTuber
git submodule update --init --recursive
uv sync
uv run run_server.py
```

首次启动时，项目可能会下载语音识别模型到 `models/`，耗时取决于网络和磁盘速度。

## 当前 LLM 配置

当前使用 DeepSeek：

```yaml
character_config:
  agent_config:
    agent_settings:
      basic_memory_agent:
        llm_provider: 'deepseek_llm'
```

DeepSeek 参数在 `conf.yaml` 的 `deepseek_llm` 段：

```yaml
deepseek_llm:
  base_url: 'https://api.deepseek.com'
  llm_api_key: '<写在本地 conf.yaml 中>'
  model: 'deepseek-v4-flash'
  temperature: 0.7
```

不要把包含 API key 的 `conf.yaml` 上传到公开仓库。

## 当前 MCP 配置

MCP 已启用：

```yaml
use_mcpp: True
mcp_enabled_servers: ["time", "ddg-search"]
```

MCP 服务定义在：

```text
mcp_servers.json
```

当前包含：

- `time`
- `ddg-search`

修改 MCP 配置后需要重启服务。

## 角色与数字人切换

前端的角色预设来自：

```text
characters/*.yaml
```

每个角色可以通过 `live2d_model_name` 指定界面显示的 Live2D 形象。

当前已配置：

- `characters/zh_米粒.yaml` 使用 `mao_pro`
- `characters/zh_翻译腔.yaml` 使用 `shizuku`

Live2D 模型注册表：

```text
model_dict.json
```

当前已注册：

- `mao_pro`
- `shizuku`

在网页中进入设置，找到“角色预设 / Character Preset”，即可切换角色。切换 `翻译腔-神经大人` 时会使用 `shizuku` 形象。

## 添加新的 Live2D 模型

1. 将 Live2D 模型目录放入：

```text
live2d-models/
```

2. 在 `model_dict.json` 中新增模型条目，`name` 要唯一。

3. 在某个 `characters/*.yaml` 中设置：

```yaml
character_config:
  live2d_model_name: '<model_dict.json 中的 name>'
```

4. 重启服务。

## 常见问题

端口被占用：

```bash
ps -ef | rg 'run_server.py|uv run run_server'
```

停止旧服务：

```bash
kill <PID>
```

如果页面能打开但麦克风不可用，请使用 `localhost` 访问。远程设备访问麦克风通常需要 HTTPS。

如果双击脚本提示找不到 `uv`，需要在 WSL 内安装 `uv`，或者先确认 WSL 终端里执行 `uv --version` 能正常输出。
