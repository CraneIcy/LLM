# Practice02 - LLM Function Call 本地文件操作 Agent

基于 DeepSeek API 的流式对话 Agent，支持 Function Call 调用本地工具完成日期查询、闰年计算和文件系统操作。

## 功能

### 对话能力
- 流式输出（打字机效果）
- 多轮上下文记忆
- 无限循环对话，Ctrl+C 退出

### 工具列表（12 个）

| 工具 | 作用 | 实现方式 |
|---|---|---|
| `getDate` | 获取当前日期时间 | 调用本地 `date /t & time /t` 命令 |
| `isLeapYear` | 判断某年是否为闰年 | Python 计算：`(y%4==0 and y%100!=0) or (y%400==0)` |
| `getCwd` | 获取当前工作目录 | `os.getcwd()` |
| `listDir` | 列出目录下文件和子目录 | `os.listdir()` |
| `getFileType` | 判断路径是文件还是文件夹 | `os.path.isfile()` / `os.path.isdir()` |
| `readFile` | 读取文件文本内容 | `open().read()` |
| `createFile` | 创建新文件（可带初始内容） | `open(path, 'w')` |
| `writeFile` | 覆盖写入文件内容 | `open(path, 'w')` |
| `makeDir` | 创建新目录 | `os.makedirs()` |
| `removeDir` | 删除非空目录 | `shutil.rmtree()` |
| `removeFile` | 删除文件 | `os.remove()` |
| `rename` | 重命名文件或目录 | `os.rename()` |

## 文件结构

```
Practice02/
├── chat.py          # 主程序
├── .config.ini      # LLM 配置（不入库）
├── .gitignore       # Git 忽略规则
├── architecture.mmd  # Mermaid 代码架构图
└── README.md        # 项目说明
```

## 运行

```bash
cd D:\LLM\Agent\Practice2
C:\ProgramData\anaconda3\python.exe chat.py
```

依赖：`pip install requests`

## 配置

编辑 `.config.ini`：

```ini
[llm]
api_key = 你的DeepSeek密钥
base_url = https://api.deepseek.com/v1
model = deepseek-chat
```

## 工作流程

```
用户输入 → 发送请求(带tools) → 流式接收响应
                                    ↓
                            模型返回 tool_calls?
                              ↙        ↘
                            否          是
                            ↓            ↓
                    打印回复结束    执行对应工具函数
                                      ↓
                                结果发回模型
                                      ↓
                                再次请求直到无工具调用
```
