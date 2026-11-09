# AnythingLLM 文档上传网页

一个单文件的本地网页（`上传文档到AnythingLLM.html`），用于把本地文档上传到 AnythingLLM 的指定工作区并完成解析与向量化，适合不熟悉 AnythingLLM 后台操作的使用者。

## 功能

1. **密钥设置**：页面顶部输入 AnythingLLM API Key，保存在浏览器 `localStorage`，源码中不含任何密钥。
2. **工作区选择**：下拉框数据来自 `GET /api/v1/workspaces`，切换工作区会刷新下方文档列表。
3. **上传并向量化**：拖拽或选择文件后提交 `POST /api/v1/document/upload`，表单带 `addToWorkspaces` 字段，上传成功后自动刷新列表。
4. **已嵌入文档列表**：调用 `GET /api/v1/workspace/{slug}` 读取 `workspace[0].documents`，展示标题、字数与发布日期。
5. **三态反馈**：请求中显示 spinner 与「上传中」，成功显示绿色「成功」徽标与 HTTP 状态，失败显示红色「失败」徽标与返回体。

## 使用步骤

1. 启动 AnythingLLM（默认 `http://localhost:3001`），在「设置 → API 密钥」生成 Key。
2. 用浏览器打开 `上传文档到AnythingLLM.html`。
3. 在「API 密钥」输入框粘贴 Key 并点击「保存」，右上角状态变为「服务在线」。
4. 选择目标工作区 → 选择文件 → 点击「上传并向量化」。

## 调用的接口

| 接口 | 方法 | 用途 |
|---|---|---|
| `/api/v1/workspaces` | GET | 读取工作区列表 |
| `/api/v1/workspace/{slug}` | GET | 读取工作区已嵌入文档 |
| `/api/v1/document/upload` | POST（multipart） | 上传文件并加入工作区向量化 |

请求头统一为 `Authorization: Bearer <本地保存的 Key>`。

## 安全说明

- 密钥不写入页面静态代码，只存在当前浏览器的 `localStorage`，换设备需要重新填写。
- 文档标题、工作区名称等来自接口的数据统一经 `escapeHtml` 转义后再渲染，避免 XSS。
- 页面默认请求 `http://localhost:3001`，如需连接远程 AnythingLLM，修改脚本顶部的 `API` 常量即可。

## 已知限制

- 需要 AnythingLLM 与浏览器在同一台机器（或已放行跨域），否则会被 CORS 拦截。
- 单文件上传，暂不支持批量拖入多个文件。
