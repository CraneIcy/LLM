"""
网页读取工具：抓取静态网页正文并转成纯文本，供模型阅读。
"""

import html
import re

import requests

from .base import BaseTool

# 默认返回字符上限，避免整页 HTML 撑爆上下文
DEFAULT_MAX_CHARS = 4000
MAX_MAX_CHARS = 8000

_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")


def _html_to_text(raw: str) -> str:
    """把 HTML 转成便于阅读的纯文本：去脚本样式、去注释、去标签、压缩空白。"""
    text = _SCRIPT_RE.sub(" ", raw)
    text = _COMMENT_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    return _BLANK_RE.sub("\n\n", "\n".join(lines)).strip()


class FetchWebTool(BaseTool):
    name = "fetchWeb"
    description = (
        "读取指定网页的正文内容。抓取静态 HTML 后去掉标签返回纯文本，"
        "适合阅读文档页、公告页、博客文章；纯前端渲染（需要执行 JS）的页面可能读不到正文。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要读取的网页地址，必须以 http:// 或 https:// 开头",
            },
            "maxChars": {
                "type": "integer",
                "description": f"返回的最大字符数，默认 {DEFAULT_MAX_CHARS}，允许范围 200 到 {MAX_MAX_CHARS}",
            },
        },
        "required": ["url"],
    }

    def execute(self, url: str, maxChars: int = DEFAULT_MAX_CHARS, **kwargs) -> str:
        # 参数校验：地址必须是完整的 http(s) 链接
        if not isinstance(url, str) or not url.strip().lower().startswith(("http://", "https://")):
            return "错误：url 必须以 http:// 或 https:// 开头，例如 https://example.com/page"

        try:
            limit = int(maxChars)
        except (TypeError, ValueError):
            limit = DEFAULT_MAX_CHARS
        limit = max(200, min(limit, MAX_MAX_CHARS))

        try:
            resp = requests.get(
                url.strip(),
                timeout=15,
                headers={"User-Agent": "CAgent/1.0 (+web fetch tool)"},
            )
        except requests.exceptions.Timeout:
            return "错误：读取网页超时（超过 15 秒）"
        except requests.exceptions.ConnectionError:
            return "错误：无法连接目标网站，请检查网络或地址是否正确"
        except requests.exceptions.MissingSchema:
            return "错误：缺少 http:// 或 https:// 前缀"
        except Exception as e:
            return f"错误：读取网页失败 - {e}"

        if resp.status_code != 200:
            return f"错误：目标页面返回 HTTP {resp.status_code}"

        # 中文站点常缺少 charset 声明，用 apparent_encoding 兜底，避免乱码
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding or "utf-8"

        text = _html_to_text(resp.text)
        if not text:
            return "错误：页面没有可读正文（可能是需要执行 JavaScript 的动态页面）"

        if len(text) > limit:
            return text[:limit] + f"\n...（已截断，正文共 {len(text)} 字符）"
        return text
