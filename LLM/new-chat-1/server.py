"""AnythingLLM MCP Server（MVP）

- 协议版本: MCP 2026-07-28（无状态核心）
- 传输: HTTP（Streamable HTTP），端点 /mcp，仅绑定 127.0.0.1
- 唯一功能: workspace_ask —— 用 AnythingLLM 工作区知识库回答提问（RAG）

环境变量:
    ANYTHINGLLM_BASE_URL    默认 http://localhost:3001
    ANYTHINGLLM_API_KEY     必填，AnythingLLM 设置页创建
    ANYTHINGLLM_WORKSPACE   可选，指定工作区 slug，缺省取列表第一个
    MCP_HOST / MCP_PORT     默认 127.0.0.1 / 8765
"""

import os

import httpx
from mcp.server import MCPServer

mcp = MCPServer("anythingllm-mcp")

BASE_URL = os.environ.get("ANYTHINGLLM_BASE_URL", "http://localhost:3001").rstrip("/")
API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "")
WORKSPACE_SLUG = os.environ.get("ANYTHINGLLM_WORKSPACE", "")


@mcp.tool()
def workspace_ask(question: str) -> str:
    """使用 AnythingLLM 工作区中已导入的知识回答提问（仅基于知识库，不开放闲聊）。

    Args:
        question: 要向 AnythingLLM 工作区知识库提出的问题。
    """
    if not API_KEY:
        return "错误：未配置 ANYTHINGLLM_API_KEY，请先在 AnythingLLM 设置页创建 API Key 并设置环境变量。"

    headers = {"Authorization": f"Bearer {API_KEY}"}
    try:
        with httpx.Client(timeout=120) as client:
            resp = client.get(f"{BASE_URL}/api/v1/workspaces", headers=headers)
            if resp.status_code in (401, 403):
                return f"错误：AnythingLLM 鉴权失败（HTTP {resp.status_code}），请检查 API Key 是否正确。"
            resp.raise_for_status()

            workspaces = resp.json().get("workspaces", [])
            if not workspaces:
                return "错误：AnythingLLM 中还没有任何工作区，请先创建工作区并导入文档。"

            if WORKSPACE_SLUG:
                if not any(w.get("slug") == WORKSPACE_SLUG for w in workspaces):
                    available = ", ".join(w.get("slug") for w in workspaces)
                    return f"错误：ANYTHINGLLM_WORKSPACE 指定的工作区 '{WORKSPACE_SLUG}' 不存在，可用工作区: {available}"
                slug = WORKSPACE_SLUG
            else:
                slug = workspaces[0]["slug"]

            chat = client.post(
                f"{BASE_URL}/api/v1/workspace/{slug}/chat",
                headers=headers,
                json={"message": question, "mode": "query"},
            )
            if chat.status_code in (401, 403):
                return f"错误：AnythingLLM 鉴权失败（HTTP {chat.status_code}），请检查 API Key 是否正确。"
            chat.raise_for_status()
            return chat.json().get("textResponse") or "（AnythingLLM 未返回回答文本）"
    except httpx.HTTPError as e:
        return f"错误：无法连接 AnythingLLM（{BASE_URL}），请确认其正在运行。{e}"
    except Exception as e:  # 兜底，保证工具永远返回可读结果
        return f"错误：{e}"


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_PORT", "8765")),
        stateless_http=True,
        json_response=True,
    )
