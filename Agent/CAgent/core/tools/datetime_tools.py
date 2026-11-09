"""
日期时间相关工具：getDate、isLeapYear。
"""

from datetime import datetime

from .base import BaseTool

# 星期与中文名称的映射（避免硬编码拼接错误）
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class GetDateTool(BaseTool):
    name = "getDate"
    description = "获取当前电脑的日期和时间（读取本机系统时钟，跨平台可用）"
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> str:
        # 直接读取系统时钟并换算到本地时区：
        # 不写死日期，也不依赖某一平台的 shell 命令，Windows / macOS / Linux 行为一致。
        now = datetime.now().astimezone()
        tz_label = now.tzname() or "本地时区"
        return (
            f"{now:%Y-%m-%d} {_WEEKDAYS[now.weekday()]} "
            f"{now:%H:%M:%S}（{tz_label}，UTC{now:%z}）"
        )


class IsLeapYearTool(BaseTool):
    name = "isLeapYear"
    description = "判断给定的年份是否为闰年"
    parameters = {
        "type": "object",
        "properties": {
            "year": {"type": "integer", "description": "要判断的年份，例如 2024"},
        },
        "required": ["year"],
    }

    def execute(self, year: int, **kwargs) -> str:
        # 闰年规则：能被 4 整除且不能被 100 整除，或者能被 400 整除（整百年单独判定）
        result = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        return f"{year} 年是{'闰年' if result else '平年'}"
