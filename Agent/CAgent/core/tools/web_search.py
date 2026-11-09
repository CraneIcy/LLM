"""
网络搜索工具：通过百度千帆 AI Search API 获取互联网最新信息。
"""

import json
import requests

from .base import BaseTool


class SearchWebTool(BaseTool):
    name = "searchWeb"
    description = "搜索互联网获取最新信息，适合查询实时新闻、最新动态、不知道的知识等"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或问题，例如：2024年最新科技新闻、Python最新版本",
            }
        },
        "required": ["query"],
    }

    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url

    def execute(self, query: str, **kwargs) -> str:
        # 配置检查
        if not self.api_key:
            return "错误：未配置百度千帆搜索 API Key，请在 .config.ini 的 [search] 段设置 baidu_qianfan_api_key"

        try:
            resp = requests.post(
                url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "messages": [
                        {"role": "user", "content": query}
                    ],
                    "stream": False,
                    "conversation_id": "",
                },
                timeout=30,
            )
        except requests.exceptions.ConnectionError:
            return "错误：网络连接失败，请检查网络是否正常"
        except requests.exceptions.Timeout:
            return "错误：搜索请求超时，请稍后重试"
        except Exception as e:
            return f"错误：网络请求异常 - {e}"

        # HTTP 状态码检查
        if resp.status_code != 200:
            try:
                err = resp.json()
                err_msg = err.get("error", {}).get("message", resp.text[:200])
            except Exception:
                err_msg = resp.text[:200]
            return f"错误：搜索 API 返回 {resp.status_code} - {err_msg}"

        # 解析返回结果（百度千帆 AI Search 直接返回 references 数组）
        try:
            data = resp.json()
            references = data.get("references", [])
        except (json.JSONDecodeError, AttributeError) as e:
            return f"错误：解析搜索结果失败 - {e}"

        if not references:
            return f"搜索「{query}」未找到相关结果"

        # 整理搜索结果摘要 + 参考来源
        lines = [f"【搜索结果】{query}", ""]
        for i, ref in enumerate(references[:8], 1):
            title = ref.get("title", "无标题")
            snippet = ref.get("snippet", ref.get("content", ""))[:200]
            url = ref.get("url", "")
            website = ref.get("website", "")
            lines.append(f"[{i}] {title}（{website}）")
            lines.append(f"    {snippet}")
            lines.append(f"    链接: {url}")
            lines.append("")

        return "\n".join(lines)
