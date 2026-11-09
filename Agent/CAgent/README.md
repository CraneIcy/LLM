# CAgent · 定制 Function Call Agent

基于大语言模型的工具型 Agent，采用 **core / ui 分层架构**，同一套核心逻辑可跑在桌面窗口（Tkinter GUI）与终端界面（Textual TUI）上。

## 一、架构分层

```text
CAgent/
├── core/                       # 业务层（不依赖任何 UI 框架）
│   ├── config.py               # 配置读取 + 缺省模板生成
│   ├── llm_client.py           # LLM 客户端：流式响应 + Function Call 多轮闭环 + AGENTS.md 注入
│   ├── tool_registry.py        # 工具注册表：Schema 导出与统一执行
│   ├── skill_loader.py         # 技能发现与按需加载（YAML frontmatter）
│   ├── mcp_client.py           # MCP 客户端：stdio / Streamable HTTP 两种传输
│   ├── context_manager.py      # Token 用量、上下文归档、全文检索
│   ├── session_manager.py      # 会话保存 / 列表 / 恢复 / 删除
│   └── tools/                  # 18 个内置工具（15 个基础 + 3 个高阶）+ MCP 工具适配器
├── ui/                         # 界面层（单向依赖 core）
│   ├── gui/app.py              # 桌面窗口（Tkinter）
│   ├── tui/app.py              # 终端界面（Textual）
│   └── cli/app.py              # 纯命令行界面
├── .agents/
│   ├── skills/                 # 技能目录（clinic-compliance / code-review / translator / writing-assistant）
│   ├── sessions/               # 会话存档（JSONL）
│   └── context/                # 上下文归档（JSONL）
├── AGENTS.md                   # 项目长期规则（启动时一次注入）
├── main.py                     # 入口
└── .config.ini                 # 本地配置（不入库，缺失时自动生成模板）
```

设计原则：

1. **单向依赖**：`ui → core`，core 不反向依赖任何 UI。
2. **回调通信**：core 通过 `on_token / on_tool_call / on_tool_result` 回调把事件推给界面。
3. **工具可插拔**：新增工具只需继承 `BaseTool` 并在 `ToolRegistry` 注册。
4. **界面可替换**：GUI / TUI / CLI 共用同一个 `LLMClient` 实例。

## 二、内置工具

共 18 个：15 个基础工具（文件 10 / 时间 2 / 命令行 1 / 网页 2）+ 3 个高阶工具
（`loadSkill` / `createSkill` / `recallContext`）。其中 `searchWeb` 需在 `.config.ini`
配置检索 Key 后才会注册，未配置时工具清单里没有它。

| 工具 | 功能 | 关键实现 |
|---|---|---|
| `getDate` | 读取本机日期时间（含星期与时区） | `datetime.now().astimezone()`，跨平台、非硬编码 |
| `isLeapYear` | 闰年判断 | `(y%4==0 and y%100!=0) or y%400==0` |
| `getCwd` | 获取当前工作目录 | `os.getcwd()` |
| `listDir` | 列出目录项（区分文件夹/文件并给大小） | `os.listdir()`，目录不存在时明确报错 |
| `getFileType` | 判断文件/目录/不存在，返回扩展名 | `os.path.isdir/isfile` |
| `readFile` | 读取文本文件 | `open(..., encoding="utf-8")`，先校验存在性 |
| `createFile` | 创建文件（可带初始内容）；同名文件会被覆盖，返回里注明原大小 | `open(path, "w")` |
| `writeFile` | 覆盖写入 | `open(path, "w")`，返回覆盖/新建与字节数 |
| `makeDir` | 创建目录（支持多级） | `os.makedirs(exist_ok=True)`，已存在时不动 |
| `removeDir` | 删除目录及其内容 | `shutil.rmtree`，**必须 `confirm=true`**；拒绝盘符根/系统目录/项目根 |
| `removeFile` | 删除文件 | `os.remove`，**必须 `confirm=true`** |
| `rename` | 重命名/移动文件或目录 | `os.rename`，目标已存在时需 `confirm=true` |
| `RunCli` | 执行本地命令行程序 | `subprocess.run(timeout=15, shell=False)`，输出截断 2000 字符 |
| `fetchWeb` | 读取静态网页正文 | `requests` + 去标签转纯文本，默认截断 4000 字符 |
| `searchWeb` | 互联网检索（配置 Key 后启用） | 百度千帆 AI Search，返回标题/摘要/链接 |
| `loadSkill` | 按需加载技能正文或附加文件 | 只允许技能目录内路径，正文上限 20000 字符 |
| `createSkill` | 按用户要求生成技能目录与 SKILL.md | 校验命名、拒绝覆盖同名技能 |
| `recallContext` | 在上下文归档中全文检索 | 关键词匹配 JSONL 归档 |

外部 MCP 工具会被包装成 `服务器名__工具名` 的形式并入同一套工具集合。

## 三、技能机制

1. **发现**：启动时扫描 `.agents/skills/*`，只解析 `SKILL.md` 开头的 YAML frontmatter（`name` + `description`）。
2. **注入**：仅把技能名称与描述写入 system prompt，不读正文，避免上下文膨胀。
3. **加载**：模型判断需要时调用 `loadSkill`，才读取正文；正文超长自动截断。
4. **创建**：`createSkill` 校验名称格式（小写字母/数字/连字符），同名存在时直接拒绝，不覆盖。

示例技能：`clinic-compliance`（动物诊疗机构合规自查，业务技能）、`code-review`（代码审查）、`translator`（翻译）、`writing-assistant`（写作润色）。

## 四、MCP 接入

配置文件 `.mcp.json`（项目根目录），支持两种传输：

```json
{
  "mcpServers": {
    "本地服务": { "type": "stdio", "command": "python", "args": ["server.py"] },
    "远程服务": { "type": "streamable_http", "url": "http://127.0.0.1:8000/mcp", "headers": {} }
  }
}
```

- 连接、发现、调用统一提交到常驻后台事件循环，保证 `ClientSession` 跨多次调用有效。
- 单个 Server 连接失败只记录状态，不阻塞主流程；界面边栏显示每个 Server 的连接状态与工具数。
- MCP 工具的参数 Schema 会被规范化为 Function Call 格式，并在描述中标注来源服务器。

## 五、会话、上下文与项目规则

- **会话**：`/save` 保存当前会话，`/new` 归档后开新会话，`/resume` 从列表恢复；文件存于 `.agents/sessions/*.jsonl`。
- **上下文**：优先使用 API 返回的 `usage` 统计；达到窗口 80% 时暂停输入并提示压缩。
- **压缩**：`/compact` 先把原始上下文完整归档到 `.agents/context/`，再用专用 Prompt 生成约 5000 Token 摘要替换历史，压缩失败则保留原上下文。
- **检索**：压缩后可用 `recallContext` 在归档中按关键词找细节。
- **AGENTS.md**：启动时读取一次并作为 system 消息常驻；支持 `AGENT.md` 等价命名，文件名可在 `[agent] agents_md_file` 配置，缺失时不报错，超过 8000 字符自动截断。

## 六、运行

```bash
pip install requests mcp textual
python main.py            # 默认桌面界面
python main.py --tui      # 终端界面
```

首次运行若没有 `.config.ini`，程序会自动生成模板并提示填写 `api_key`，修改后重启生效。

### 命令与快捷键

| 命令 | 作用 |
|---|---|
| `/new` | 保存并开始新会话 |
| `/resume` | 从历史会话列表恢复 |
| `/save` | 保存当前会话 |
| `/compact` | 归档并压缩上下文 |
| `/help` | 显示命令说明 |

TUI 快捷键：`Ctrl+C` 退出、`Ctrl+R` 清空对话。

## 七、安全边界

- 密钥只来自 `.config.ini`（不入库），不写死在代码里；缺少配置时给出明确提示并启用 mock 模板。
- 文件工具统一先做参数校验（空路径、目录/文件类型不符、上级目录不存在都直接报错，不抛裸异常）。
- 删除目录、删除文件、覆盖式重命名属于不可逆操作，必须显式传 `confirm=true`，否则只返回拦截说明、不产生副作用；盘符根、`C:\Windows` 等系统关键目录与当前项目根一律拒绝。
- `RunCli` 使用 `shell=False` + 15 秒超时，避免命令注入与卡死；输出自动截断。
- `loadSkill` 的附加文件读取限定在技能目录内，阻止路径穿越。
- 单轮对话最多允许 8 轮工具调用（`[agent] max_tool_steps`），防止模型死循环。

## 八、自测脚本

根目录的 `test_*.py`（`test_startup` / `test_tui_smoke` / `test_gui_smoke` /
`test_e2e_real` / `test_compact_integration` / `test_context_manager` /
`test_new_features`）是**手动运行的自测脚本**（`python test_xxx.py`），不是 pytest 用例，
共约 34 处 `assert`；MCP 集成期的一次性排查脚本已归档到 `scripts/debug/`，
不参与任何测试收集。
