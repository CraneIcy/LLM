"""
命令行交互界面：简单可靠，适合打包后使用。
"""

import sys
from ui.base import BaseUI
from core.llm_client import LLMClient


class CLIUI(BaseUI):
    """简单命令行交互界面。"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def run(self):
        print("=" * 50)
        print("  CAgent - 命令行模式")
        print("  输入 'exit' 或 'quit' 退出")
        print("=" * 50)
        print()

        while True:
            try:
                user_input = input("你 › ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "退出"):
                    print("再见！")
                    break

                print("CAgent › ", end="", flush=True)

                # 流式输出
                for chunk in self.llm_client.chat_stream(user_input):
                    print(chunk, end="", flush=True)

                print()
                print()

            except KeyboardInterrupt:
                print("\n再见！")
                break
            except Exception as e:
                print(f"\n错误: {e}")
                print()
