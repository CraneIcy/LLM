# UPGRADE_PROMPT — 扩展本 MCP 服务的约定

> 本文是**扩展约定**，不是现状清单。现状以 [`README.md`](README.md) 与
> [`src/pet_hospital_mcp/server.py`](src/pet_hospital_mcp/server.py) 为准：
> 目前已注册两个工具 `list_pets`、`get_pet_records`，并已有 6 个文件、66 项 pytest。
> 任何新增工具都应遵守下面同一套约定，避免重新发明传输层与错误层。

## 一、当前已实现（现状）

| 项 | 现状 | 位置 |
|---|---|---|
| 工具 | `list_pets`（14 参数，列表/过滤/排序/分页）、`get_pet_records`（病历时间线 + 六字段自查） | `tools/list_pets.py`、`tools/get_pet_records.py` |
| 传输 | Streamable HTTP，stateless（无 `initialize`、无 `Mcp-Session-Id`） | `server.py` `streamable_http_app(stateless_http=True)` |
| 健康检查 | `/health` 返回 SDK/协议版本、传输方式、上游可达性 | `server.py` `custom_route("/health")` |
| 错误层 | `VALIDATION_ERROR` / `BACKEND_TIMEOUT` / `BACKEND_UNAVAILABLE` / `BACKEND_API_ERROR` / `BACKEND_INVALID_RESPONSE` / `INTERNAL_ERROR` | `errors.py` |
| 日志 | 结构化日志 + 敏感字段脱敏 | `logging_config.py` |
| 测试 | 5 个测试文件 + `conftest.py`，`pytest -q` 输出 66 passed | `tests/` |

## 二、新增一个只读工具的步骤

1. 在 `src/pet_hospital_mcp/tools/` 新建一个模块，文件名即工具语义（如 `list_charges.py`）。
2. 定义 `Input` / `Success` 两个 Pydantic 模型；失败一律复用 `ErrorEnvelope`，
   最终用 `ErrorEnvelope.to_dict()` 返回，不抛裸异常。
3. 暴露 `register(mcp, rest_client)`，用 `@mcp.tool(name=..., description=...)` 注册；
   `server.py` 里只需新增一行 `xxx.register(mcp, rest_client)`。
4. 上游调用一律走 `PetHospitalRESTClient`（工具代码里不要直接 `import httpx`），
   超时与重试由客户端统一负责。
5. 用 `build_tool_log_entry` 写一条结构化日志，参数与结果都做脱敏。
6. 在 `tests/` 补：参数校验（越界/类型错）、上游 4xx、上游 5xx 重试、非 JSON 响应四类用例。
7. 同步更新 `README.md` 的工具表、参数表与目录树。

## 三、尚未实现（计划，勿当现状）

- `get_pet_charges`：对应 `GET /api/v1/pets/{id}/charges`，字段自查可扩展为收费项完整性。
- 写工具（`POST` / `PUT` / `DELETE`）：需要先确定幂等策略、失败回滚语义，以及
  “教学场景下是否允许 Agent 改数据”；未明确前不要动手。

## 四、不要改变的约束

- 服务保持 stateless：不引入 `initialize` 握手、不写会话存储。
- 默认只监听 `127.0.0.1`。
- 不修改 Go 后端的代码与接口语义；后端字段变更通过适配层消化。
