# 动物诊疗机构合规自查 Agent · 大语言模型技术与应用期末项目

本仓库只做一个场景的 Agent：**帮助动物诊疗机构做合规自查**。
机构在迎检、质控、年度报告时会遇到同一类麻烦——病历、处方、公示、报告义务散落在业务系统和一堆法规文件里，人工比对又慢又容易漏。这个 Agent 把两边接起来：从业务系统取真实病历与收费记录，从知识库取法规条文，逐条比对后给出带条款出处的问题清单。

依据文本：《中华人民共和国动物防疫法》第七章「动物诊疗」（第六十一至六十三条）、《动物诊疗机构管理办法》（农业农村部令 2022 年第 5 号，2022 年 10 月 1 日施行）。

为了这一个场景，仓库包含四块相互衔接的部件：

| 编号 | 部件 | 目录 | 技术栈 | 在本场景中的职责 |
|---|---|---|---|---|
| A | 宠物医院 MCP Server | `PetHospitalMCP/pet-hospital-mcp` | Python 3.11 + mcp 2.x SDK | 把 Go 版诊疗机构 REST API 封装成 MCP 工具：查档案、查病历并做字段自查 |
| B | AnythingLLM MCP Server | `new-chat-1` | Python + mcp 2.x SDK + httpx | 把法规知识库（工作区/文档/检索问答）封装成 MCP 工具，供 Agent 引条文 |
| C | AnythingLLM 文档上传网页 | `AnythingLLMSever` | 原生 HTML/CSS/JS | 让机构把新规、检查表、模板自己传进知识库 |
| D | 定制 Agent | `Agent/CAgent` | Python + DeepSeek/OpenAI 兼容接口 | 编排上面三类能力，按自查清单出结论 |

另外 `Agent/Practice01`、`Agent/Practice2` 是课程过程性练习，`PetHospitalMCP` 根目录是 Go 后端源码。

## 一、目录结构

```text
LLM/
├── Agent/
│   ├── Practice01/              # 练习一：流式对话（chat.py）
│   ├── Practice2/              # 练习二：Function Call 12 个工具（chat.py + architecture.mmd）
│   └── CAgent/                 # 定制 Agent（期末主交付）
│       ├── core/               # 业务层：config / llm_client / tool_registry / skill_loader
│       │   │                   #        / mcp_client / context_manager / session_manager
│       │   └── tools/          # 14 个本地工具 + MCP 工具适配器
│       ├── ui/                 # 界面层：tui（Textual）/ gui（桌面窗口）/ cli
│       ├── .agents/skills/     # 技能目录（含 clinic-compliance 合规自查等 4 个技能）
│       ├── AGENTS.md           # 项目长期规则（启动时一次注入，含业务边界与条款引用规则）
│       └── main.py             # 入口：python main.py（默认 GUI，--tui 切终端）
├── PetHospitalMCP/
│   ├── main.go                 # Go 后端入口（29 个 REST 接口，网页内嵌进二进制）
│   ├── internal/api|model|store# 路由、模型、单文件存储引擎
│   └── pet-hospital-mcp/       # Python MCP Server（list_pets / get_pet_records 两个工具）
├── AnythingLLMSever/
│   └── 上传文档到AnythingLLM.html   # 文档上传网页（密钥存本机 localStorage）
├── new-chat-1/                 # AnythingLLM MCP Server（4 个工具）
└── README.md
```

## 二、快速开始

### 0. 前置条件

- Windows / macOS / Linux，Python 3.11+
- Go 1.22+（仅重新编译宠物医院后端时需要）
- AnythingLLM 已在 `http://localhost:3001` 运行（B、C 两个模块依赖）
- 一个大模型 API Key（DeepSeek / OpenAI 兼容接口均可，D 模块需要）

### 1. 宠物医院 Go 后端（A 的上游）

```bash
cd PetHospitalMCP
go run . -seed          # 首次运行写入示例数据，服务监听 127.0.0.1:8080
```

浏览器打开 `http://127.0.0.1:8080/` 可看到内置操作界面；`GET /api/v1/endpoints` 返回全部接口清单。

### 2. 宠物医院 MCP Server（A）

```bash
cd PetHospitalMCP/pet-hospital-mcp
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m pet_hospital_mcp          # 监听 127.0.0.1:8000，MCP 端点为 /mcp
```

### 3. AnythingLLM MCP Server（B）

```bash
cd new-chat-1
pip install -r requirements.txt
copy .env.example .env              # macOS/Linux 用 cp，然后填入 ANYTHINGLLM_API_KEY
python server.py                    # 监听 127.0.0.1:8765，端点为 /mcp
```

### 4. AnythingLLM 文档上传网页（C）

直接用浏览器打开 `AnythingLLMSever/上传文档到AnythingLLM.html`，在弹出的「API 密钥」输入框填入 AnythingLLM 的 API Key（只保存在本机 localStorage），即可选择工作区、上传文件并向量化。

### 5. 定制 Agent（D）

```bash
cd Agent/CAgent
pip install requests mcp textual
python main.py                      # 默认桌面界面；python main.py --tui 使用终端界面
```

首次运行若缺少 `.config.ini`，程序会自动生成模板并提示填写 `api_key`，修改后重启即可。

## 三、配置与密钥

| 模块 | 配置载体 | 是否入库 |
|---|---|---|
| CAgent | `.config.ini`（缺省自动生成模板，字段表见 `core/config.py`） | 否，已被 `.gitignore` 忽略 |
| PetHospital MCP | 环境变量（`PET_HOSPITAL_BASE_URL`、`MCP_PORT`、`BACKEND_TIMEOUT_SECONDS` 等） | 无密钥 |
| AnythingLLM MCP | `.env`（模板见 `new-chat-1/.env.example`） | 否 |
| 上传网页 | 浏览器 localStorage | 否，源码中不含密钥 |

仓库中的 `.gitignore` 已排除 `*.exe`、`*.db`、`.venv/`、`__pycache__/`、`.env`、`.config.ini` 等产物与密钥文件，真实密钥不入库。

## 四、验证清单

| 验证项 | 操作 | 预期 |
|---|---|---|
| Go 后端存活 | `curl http://127.0.0.1:8080/health` | 返回 `status: ok` |
| A：MCP 健康检查 | `curl http://127.0.0.1:8000/health` | 返回 `transport: streamable-http`、`upstream: ok` |
| A：工具可枚举 | `POST http://127.0.0.1:8000/mcp`，`tools/list` | 返回 `list_pets` 与 `get_pet_records` 及其参数 Schema |
| A：单元测试 | `cd PetHospitalMCP/pet-hospital-mcp && pytest -v` | 66 项全部通过（使用 MockTransport，无需真实后端） |
| B：工具可枚举 | 客户端连 `http://127.0.0.1:8765/mcp`，`tools/list` | 返回 4 个工具 |
| C：上传闭环 | 网页选择文件 → 上传并向量化 | 结果区显示 HTTP 200 与 success，文档列表出现新文档 |
| D：Agent 启动 | `python main.py --tui` | 界面显示工具数、技能数、MCP 服务器状态 |
| D：工具调用闭环 | 输入「现在几点」「2024 年是闰年吗」 | 触发 `getDate` / `isLeapYear` 并回填结果 |
| D：技能渐进加载 | 输入「用 code-review 技能审查 main.py」 | 先注入名称与描述，调用 `loadSkill` 后才读取正文 |
| 场景闭环 | 输入「用 clinic-compliance 技能自查档案 p-001 的病历」 | 调 `get_pet_records` 取证 → 检索法规条文 → 输出带条款出处的问题清单 |

## 五、各模块文档

- `Agent/CAgent/README.md`：Agent 架构、工具、技能、MCP、会话与上下文
- `PetHospitalMCP/README.md`：Go 后端接口与网页界面
- `PetHospitalMCP/pet-hospital-mcp/README.md`：MCP 工具契约、错误码、测试
- `new-chat-1/README.md`：AnythingLLM MCP 工具与调用示例
- `AnythingLLMSever/README.md`：上传网页的功能、接口与安全说明
