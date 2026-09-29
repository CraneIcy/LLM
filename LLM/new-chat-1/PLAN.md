# AnythingLLM MCP Server — MVP 开发计划

> 范围：只实现**一个**功能 —— 选定工作区（默认第一个）提取知识进行 AI 回答。不做冗余设计。

## 1. 目标

在 `new-chat-1` 目录开发一个 Python MCP Server：

- 协议版本：**MCP 2026-07-28**（当前规范，无状态核心）
- 传输：**HTTP（Streamable HTTP）**，不用 stdio
- 唯一工具：`workspace_ask(question)` —— 用 AnythingLLM 的工作区知识库做 RAG 问答，返回 AI 回答文本

## 2. 已核实的事实（2026-09-22）

| 项 | 结论 |
|---|---|
| AnythingLLM 本机地址 | `http://localhost:3001`（API 文档 `/api/docs` 可达；无 Key 访问返回 403，鉴权生效） |
| 列工作区 | `GET /api/v1/workspaces` → `{workspaces:[{id,name,slug,...}]}` |
| 工作区问答 | `POST /api/v1/workspace/{slug}/chat`，body `{message, mode:"query"}` → `{textResponse, sources,...}` |
| MCP 2026-07-28 要点 | 无 `initialize` 握手、`server/discover` 发现；单 POST 端点；每请求必带 `MCP-Protocol-Version` + `Mcp-Method`（`tools/call` 另需 `Mcp-Name`）；服务端校验 Origin、建议仅绑定 127.0.0.1 |
| Python SDK | `mcp` v2 稳定版（2.0.0 于 2026-07-28 发布，现最新 2.2.0），一个端点同时应答 2026-07-28 与旧版客户端 |
| 本机 Python | 3.14.7（≥3.10，满足要求） |

## 3. 技术选型

- Python 3.10+；依赖仅两个：`mcp[cli]>=2.0,<3`、`httpx`（SDK 自带协议实现与 HTTP 服务，httpx 调 AnythingLLM）
- 启动：`mcp.run(transport="streamable-http", host="127.0.0.1", port=8765, stateless_http=True, json_response=True)`
  - 端点 `/mcp`（SDK 默认）；端口 8765 避开 AnythingLLM 的 3001
  - `stateless_http=True` 对应 2026-07-28 无状态模式；`json_response=True` 使每次 POST 返回单个 JSON（工具为同步单次回答，无需 SSE，便于测试）
- 协议合规（server/discover、版本协商、请求头校验、错误码）**全部交给 SDK**，不自造 JSON-RPC

## 4. 目录结构（最小）

```
new-chat-1/
├── server.py          # 全部逻辑：MCPServer + 1 个工具（约 70 行）
├── requirements.txt
└── README.md          # API Key 获取、环境变量、运行与测试
```

不引入 dotenv、不拆模块、不做配置类。

## 5. 唯一功能设计

**工具**：`workspace_ask(question: str) -> str`

流程：
1. `GET /api/v1/workspaces`（`Authorization: Bearer $ANYTHINGLLM_API_KEY`）
2. 选工作区：环境变量 `ANYTHINGLLM_WORKSPACE`（slug）优先，否则取列表**第一个**；列表为空 → 返回明确错误
3. `POST /api/v1/workspace/{slug}/chat`，body `{"message": question, "mode": "query"}`
   - `mode:"query"` = 只基于工作区已嵌入知识回答（对应"提取信息进行 AI 回答"）
4. 返回 `textResponse`；AnythingLLM 出错（无 Key / 401 / 403 / 4xx / 5xx）→ 转为带提示的工具错误，不裸抛 traceback

**环境变量**：

| 变量 | 默认 | 说明 |
|---|---|---|
| `ANYTHINGLLM_BASE_URL` | `http://localhost:3001` | |
| `ANYTHINGLLM_API_KEY` | 无（必填） | 在 AnythingLLM 设置页创建 |
| `ANYTHINGLLM_WORKSPACE` | 无（默认第一个） | 可选，按 slug 指定工作区 |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8765` | |

## 6. 实现要点

- httpx.Client 设超时（如 120s，LLM 回答较慢）
- 只绑定 localhost（符合规范安全建议）
- 入口 `if __name__ == "__main__":` 保护（`mcp dev` / 测试时以 import 方式加载）

## 7. 验证方式

1. `pip install -r requirements.txt`；设置环境变量后 `python server.py`；或 `mcp dev server.py` 打开 Inspector 调试
2. HTTP 直测（curl）：
   - `POST /mcp`（带 `MCP-Protocol-Version: 2026-07-28`、`Mcp-Method` 头）`server/discover` → supportedVersions 含 2026-07-28
   - `tools/list` → 可见 `workspace_ask`
   - `tools/call`（带 `Mcp-Name` 头）`workspace_ask` → 返回答案文本
3. 负向用例：错 Key、无工作区、工作区无数据 → 各自返回明确错误
4. 端到端：真实 MCP 客户端（Claude Desktop / Cursor 等）配置指向 `http://127.0.0.1:8765/mcp` 实测

## 8. 明确不做（防过度设计）

- 不做多工具、多工作区选择、流式输出、会话/记忆、缓存、鉴权扩展、部署脚本
- 不解析转发 sources、不做 SSE 自定义、不写 .env 加载器

## 9. 风险与前置

- 【待办·用户】在 AnythingLLM 中创建 API Key（设置 → API Keys）
- 工作区需至少含一个已嵌入文档的模型（有数据才能"提取信息"）
- 如需允许开放问答（非纯知识库），后续可给工具加 `mode:"chat"` 选项
