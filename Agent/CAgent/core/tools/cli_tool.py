"""
本地命令行工具：通过 subprocess 执行任意本地 CLI 程序。
教学实验环境，不做白名单/黑名单/审批限制。
"""

import subprocess

from .base import BaseTool


class RunCliTool(BaseTool):
    name = "RunCli"
    description = "执行本地命令行程序（CLI），可以运行任何已安装的命令行工具"
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的程序名称，例如 python、git、dir、ipconfig",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "命令参数列表，每个参数作为数组的一个元素，例如 ['--version']",
            },
        },
        "required": ["command"],
    }

    def execute(self, command: str, args: list = None, **kwargs) -> str:
        if args is None:
            args = []

        # 组装完整命令列表（shell=False，避免命令注入）
        cmd_list = [command] + args

        try:
            result = subprocess.run(
                cmd_list,
                capture_output=True,
                text=True,
                timeout=15,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return f"命令执行超时（超过15秒）：{' '.join(cmd_list)}"
        except FileNotFoundError:
            return f"错误：找不到命令 '{command}'，请确认程序已安装且在 PATH 中"
        except Exception as e:
            return f"错误：执行命令失败 - {e}"

        # 截断过长输出，避免占用上下文
        max_len = 2000
        stdout = result.stdout or ""
        stderr = result.stderr or ""

        stdout_truncated = len(stdout) > max_len
        stderr_truncated = len(stderr) > max_len

        if stdout_truncated:
            stdout = stdout[:max_len] + f"\n...（已截断，共 {len(result.stdout)} 字符）"
        if stderr_truncated:
            stderr = stderr[:max_len] + f"\n...（已截断，共 {len(result.stderr)} 字符）"

        # 组装返回结果
        output = f"执行命令: {' '.join(cmd_list)}\n"
        output += f"退出码: {result.returncode}\n"

        if stdout:
            output += f"\n[stdout]\n{stdout}\n"
        if stderr:
            output += f"\n[stderr]\n{stderr}\n"

        if not stdout and not stderr:
            output += "(无输出)"

        return output
