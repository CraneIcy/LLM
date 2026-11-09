"""AnythingLLM MCP Server

- 协议版本: MCP 2026-07-28（无状态核心）
- 传输: HTTP（Streamable HTTP），端点 /mcp，默认仅绑定 127.0.0.1
- 能力覆盖:
    工作区管理  list_workspaces
    文档管理    list_documents
    文档向量化  upload_document
    检索问答    workspace_ask

环境变量:
    ANYTHINGLLM_BASE_URL    默认 http://localhost:3001
    ANYTHINGLLM_API_KEY     必填，AnythingLLM 设置页创建
    ANYTHINGLLM_WORKSPACE   可选，默认工作区 slug，缺省取列表第一个
    MCP_HOST / MCP_PORT     默认 127.0.0.1 / 8765

错误约定：所有工具都不抛裸异常，统一返回 "错误：[错误码] 可读说明"，
错误码取值 CONFIG_ERROR / AUTH_ERROR / NOT_FOUND / UPSTREAM_ERROR / LOCAL_FILE_ERROR。
"""

import os

import httpx
from mcp.server import MCPServer

mcp = MCPServer("anythingllm-mcp")

BASE_URL = os.environ.get("ANYTHINGLLM_BASE_URL", "http://localhost:3001").rstrip("/")
API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "")
WORKSPACE_SLUG = os.environ.get("ANYTHINGLLM_WORKSPACE", "")

# 单次上传文件大小上限（20 MB），避免把超大文件灌进向量库
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# 请求超时：普通查询 60s，上传向量化 180s
QUERY_TIMEOUT = 60
UPLOAD_TIMEOUT = 180


def _err(code: str, message: str) -> str:
    """统一的错误返回格式，便于模型与调用方识别失败原因。"""
    return f"错误：[{code}] {message}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}"}


def _check_config() -> str:
    """公共配置校验，返回空字符串表示通过，否则返回错误文本。"""
    if not API_KEY:
        return _err(
            "CONFIG_ERROR",
            "未配置 ANYTHINGLLM_API_KEY，请先在 AnythingLLM 设置页创建 API Key 并设置环境变量。",
        )
    return ""


def _resolve_slug(client: httpx.Client, workspace: str = "") -> tuple:
    """解析目标工作区 slug。

    :param workspace: 用户指定的 slug，为空则用环境变量，再为空则取第一个工作区。
    :return: (slug, error_message)，error_message 为空表示成功。
    """
    resp = client.get(f"{BASE_URL}/api/v1/workspaces", headers=_headers())
    if resp.status_code in (401, 403):
        return "", _err("AUTH_ERROR", f"AnythingLLM 鉴权失败（HTTP {resp.status_code}），请检查 API Key。")
    if resp.status_code != 200:
        return "", _err("UPSTREAM_ERROR", f"获取工作区列表失败（HTTP {resp.status_code}）。")

    workspaces = resp.json().get("workspaces", [])
    if not workspaces:
        return "", _err("NOT_FOUND", "AnythingLLM 中还没有任何工作区，请先创建工作区并导入文档。")

    wanted = (workspace or WORKSPACE_SLUG).strip()
    if wanted:
        if not any(w.get("slug") == wanted for w in workspaces):
            available = ", ".join(w.get("slug", "") for w in workspaces)
            return "", _err("NOT_FOUND", f"工作区 '{wanted}' 不存在，可用工作区: {available}")
        return wanted, ""
    return workspaces[0]["slug"], ""


@mcp.tool()
def list_workspaces() -> str:
    """列出 AnythingLLM 中全部工作区（名称、slug、已嵌入文档数），用于选择后续操作的目标工作区。"""
    config_error = _check_config()
    if config_error:
        return config_error

    try:
        with httpx.Client(timeout=QUERY_TIMEOUT) as client:
            resp = client.get(f"{BASE_URL}/api/v1/workspaces", headers=_headers())
            if resp.status_code in (401, 403):
                return _err("AUTH_ERROR", f"AnythingLLM 鉴权失败（HTTP {resp.status_code}），请检查 API Key。")
            resp.raise_for_status()
            workspaces = resp.json().get("workspaces", [])
    except httpx.HTTPError as e:
        return _err("UPSTREAM_ERROR", f"无法连接 AnythingLLM（{BASE_URL}），请确认其正在运行。{e}")

    if not workspaces:
        return _err("NOT_FOUND", "AnythingLLM 中还没有任何工作区。")

    lines = [f"共 {len(workspaces)} 个工作区："]
    for w in workspaces:
        lines.append(
            f"- {w.get('name', '（未命名）')} | slug={w.get('slug', '')} | 文档数={w.get('documentsCount', '未知')}"
        )
    return "\n".join(lines)


@mcp.tool()
def list_documents(workspace: str = "") -> str:
    """列出指定工作区中已经入库并完成向量化的文档，用于确认知识库内容。

    Args:
        workspace: 工作区 slug，留空则使用 ANYTHINGLLM_WORKSPACE 或第一个工作区。
    """
    config_error = _check_config()
    if config_error:
        return config_error

    try:
        with httpx.Client(timeout=QUERY_TIMEOUT) as client:
            slug, error = _resolve_slug(client, workspace)
            if error:
                return error

            resp = client.get(f"{BASE_URL}/api/v1/workspace/{slug}", headers=_headers())
            if resp.status_code in (401, 403):
                return _err("AUTH_ERROR", f"AnythingLLM 鉴权失败（HTTP {resp.status_code}），请检查 API Key。")
            if resp.status_code == 404:
                return _err("NOT_FOUND", f"工作区 '{slug}' 不存在。")
            resp.raise_for_status()

            blocks = resp.json().get("workspace", [])
            documents = blocks[0].get("documents", []) if blocks else []
    except httpx.HTTPError as e:
        return _err("UPSTREAM_ERROR", f"读取工作区文档失败：{e}")

    if not documents:
        return f"工作区 '{slug}' 中还没有已嵌入文档。"

    lines = [f"工作区 '{slug}' 共 {len(documents)} 个已嵌入文档："]
    for index, doc in enumerate(documents, 1):
        title = doc.get("title") or doc.get("filename") or doc.get("docpath", "（无标题）")
        lines.append(f"{index}. {title}")
    return "\n".join(lines)


@mcp.tool()
def upload_document(file_path: str, workspace: str = "") -> str:
    """把本地文件上传到 AnythingLLM 并加入指定工作区完成解析与向量化（等同于网页上传）。

    Args:
        file_path: 本地文件的绝对路径，例如 D:/资料/宠物医疗规范.pdf。
        workspace: 目标工作区 slug，留空则使用默认工作区。
    """
    config_error = _check_config()
    if config_error:
        return config_error

    path = os.path.abspath(file_path)
    if not os.path.isfile(path):
        return _err("LOCAL_FILE_ERROR", f"本地文件不存在或不是文件：{path}")
    size = os.path.getsize(path)
    if size > MAX_UPLOAD_BYTES:
        return _err("LOCAL_FILE_ERROR", f"文件过大（{size} 字节），上限为 {MAX_UPLOAD_BYTES} 字节。")

    try:
        with httpx.Client(timeout=UPLOAD_TIMEOUT) as client:
            slug, error = _resolve_slug(client, workspace)
            if error:
                return error

            with open(path, "rb") as handle:
                resp = client.post(
                    f"{BASE_URL}/api/v1/document/upload",
                    headers=_headers(),
                    files={"file": (os.path.basename(path), handle, "application/octet-stream")},
                    data={"addToWorkspaces": slug},
                )
            if resp.status_code in (401, 403):
                return _err("AUTH_ERROR", f"AnythingLLM 鉴权失败（HTTP {resp.status_code}），请检查 API Key。")
            if resp.status_code != 200:
                return _err("UPSTREAM_ERROR", f"上传失败（HTTP {resp.status_code}）：{resp.text[:200]}")

            payload = resp.json()
    except httpx.HTTPError as e:
        return _err("UPSTREAM_ERROR", f"上传请求失败：{e}")
    except OSError as e:
        return _err("LOCAL_FILE_ERROR", f"读取本地文件失败：{e}")

    if not payload.get("success"):
        return _err("UPSTREAM_ERROR", f"AnythingLLM 未确认上传成功：{payload}")

    documents = payload.get("documents", [])
    names = ", ".join(str(d.get("title") or d.get("name") or "文档") for d in documents) or os.path.basename(path)
    return f"上传并向量化成功：{names}（已加入工作区 '{slug}'）。"


@mcp.tool()
def workspace_ask(question: str, workspace: str = "") -> str:
    """使用 AnythingLLM 工作区中已导入的知识回答提问（仅基于知识库，不开放闲聊）。

    Args:
        question: 要向 AnythingLLM 工作区知识库提出的问题。
        workspace: 工作区 slug，留空则使用默认工作区。
    """
    config_error = _check_config()
    if config_error:
        return config_error
    if not question or not question.strip():
        return _err("CONFIG_ERROR", "问题不能为空。")

    try:
        with httpx.Client(timeout=120) as client:
            slug, error = _resolve_slug(client, workspace)
            if error:
                return error

            chat = client.post(
                f"{BASE_URL}/api/v1/workspace/{slug}/chat",
                headers=_headers(),
                json={"message": question, "mode": "query"},
            )
            if chat.status_code in (401, 403):
                return _err("AUTH_ERROR", f"AnythingLLM 鉴权失败（HTTP {chat.status_code}），请检查 API Key。")
            if chat.status_code != 200:
                return _err("UPSTREAM_ERROR", f"问答请求失败（HTTP {chat.status_code}）：{chat.text[:200]}")
            return chat.json().get("textResponse") or "（AnythingLLM 未返回回答文本）"
    except httpx.HTTPError as e:
        return _err("UPSTREAM_ERROR", f"无法连接 AnythingLLM（{BASE_URL}），请确认其正在运行。{e}")
    except Exception as e:  # 兜底，保证工具永远返回可读结果
        return _err("UPSTREAM_ERROR", str(e))


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_PORT", "8765")),
        stateless_http=True,
        json_response=True,
    )
