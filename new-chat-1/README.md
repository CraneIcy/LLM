# AnythingLLM MCP Server（MVP）

本地 MCP Server：通过 MCP 协议（2026-07-28，HTTP/Streamable HTTP）暴露 AnythingLLM 工作区知识库问答能力。

## 功能

用 MCP 工具覆盖 AnythingLLM 的三类能力：工作区管理、文档管理与向量化、检索问答。

| 工具 | 参数 | 作用 | 对应 AnythingLLM 接口 |
|---|---|---|---|
| `list_workspaces` | 无 | 列出全部工作区（名称、slug、文档数），用于选择目标工作区 | `GET /api/v1/workspaces` |
| `list_documents` | `workspace`（可选） | 列出指定工作区中已入库并完成向量化的文档 | `GET /api/v1/workspace/{slug}` |
| `upload_document` | `file_path`、`workspace`（可选） | 把本地文件上传到工作区，触发解析与向量化 | `POST /api/v1/document/upload`（multipart） |
| `workspace_ask` | `question`、`workspace`（可选） | 用工作区知识库回答问题（RAG，`mode=query`，不开放闲聊） | `POST /api/v1/workspace/{slug}/chat` |

`workspace` 参数留空时依次回退到环境变量 `ANYTHINGLLM_WORKSPACE`、工作区列表中的第一个。

### 错误约定

所有工具都不抛裸异常，失败时返回统一格式 `错误：[错误码] 可读说明`，便于模型判断下一步：

| 错误码 | 含义 |
|---|---|
| `CONFIG_ERROR` | 未配置 API Key，或参数为空 |
| `AUTH_ERROR` | API Key 无效（HTTP 401/403） |
| `NOT_FOUND` | 工作区不存在，或没有任何工作区 |
| `UPSTREAM_ERROR` | AnythingLLM 未启动、超时或返回非 200 |
| `LOCAL_FILE_ERROR` | 待上传文件不存在、超过 20 MB 或读取失败 |

## 前置条件

1. AnythingLLM 正在本机运行（默认 `http://localhost:3001`）。
2. 已创建 API Key：AnythingLLM 界面 → 设置 → API 密钥 → 生成新的 API 密钥。
3. 至少有一个工作区并已导入文档（否则工具会返回"没有工作区"提示）。

## 安装

```powershell
cd D:\LLM\new-chat-1
python -m pip install -r requirements.txt
```

## 配置与运行

```powershell
$env:ANYTHINGLLM_API_KEY = "你的-API-Key"      # 必填
$env:ANYTHINGLLM_BASE_URL = "http://localhost:3001"  # 可选
$env:ANYTHINGLLM_WORKSPACE = "工作区slug"      # 可选，缺省用第一个工作区
python server.py
```

启动后监听 `http://127.0.0.1:8765/mcp`。可用 `$env:MCP_PORT` 改端口。

## 接入客户端

任意 MCP 客户端（Claude Desktop、Cursor 等）配置 HTTP 服务地址：

```
http://127.0.0.1:8765/mcp
```

协议版本 `2026-07-28`，传输为 Streamable HTTP（无状态，无需会话）。

## 手动测试（curl）

```powershell
$h = @{
  "Content-Type" = "application/json"
  "Accept" = "application/json, text/event-stream"
  "MCP-Protocol-Version" = "2026-07-28"
}
# 发现
Invoke-RestMethod -Uri http://127.0.0.1:8765/mcp -Method Post -Headers ($h + @{"Mcp-Method"="server/discover"}) -Body '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{}}'
# 列工具
Invoke-RestMethod -Uri http://127.0.0.1:8765/mcp -Method Post -Headers ($h + @{"Mcp-Method"="tools/list"}) -Body '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
# 调用工具（注意 Mcp-Name 头）
Invoke-RestMethod -Uri http://127.0.0.1:8765/mcp -Method Post -Headers ($h + @{"Mcp-Method"="tools/call"; "Mcp-Name"="workspace_ask"}) -Body '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"workspace_ask","arguments":{"question":"你的问题"}}}'
```

## 一键启动 / 停止

项目根目录提供了两个脚本（均自动读取根目录 `.env` 中的配置）：

| 操作 | 方式 |
|---|---|
| 启动 | 双击 `start_mcp.bat`（或命令行执行），会打开一个「AnythingLLM-MCP」窗口运行服务 |
| 停止 | 双击 `stop_mcp.bat`（按端口结束进程），或直接关闭服务窗口 / 在窗口内按 Ctrl+C |
| 重启 | 先停后启即可 |

`.env` 内容（已含你的 API Key，可自行修改）：

```
ANYTHINGLLM_API_KEY=你的Key
ANYTHINGLLM_BASE_URL=http://localhost:3001
# 可选：MCP_PORT=8765、ANYTHINGLLM_WORKSPACE=工作区slug
```

改端口时需同步修改：`.env` 的 `MCP_PORT`、`.mcp.json` 里的 `url`。

## 项目级 MCP 配置

根目录 `.mcp.json` 已把本服务注册为项目级 MCP 服务器：

```json
{
  "mcpServers": {
    "anythingllm": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

- 支持读取项目根 `.mcp.json` 的客户端（如 Claude Code）在项目内可直接调用工具 `workspace_ask`。
- Cursor：把同样内容放到 `.cursor/mcp.json`；VS Code：放到 `.vscode/mcp.json`（键名 `servers`）。

## 常见错误

| 现象 | 原因 |
|---|---|
| 工具返回"鉴权失败" | API Key 错误或未设置 |
| 工具返回"没有工作区" | AnythingLLM 中尚无工作区 |
| 工具返回"无法连接" | AnythingLLM 未启动或端口不是 3001 |
