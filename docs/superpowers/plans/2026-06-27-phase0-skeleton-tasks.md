# Phase 0 骨架 — 详细任务清单

- 日期：2026-06-27
- 依赖 spec：`docs/superpowers/specs/2026-06-27-ai-tuanbo-canvas-design.md`
- 目标：验证并行架构本身，业务全部 mock。通过 5 条验收标准。
- 构建顺序：自底向上 storage → orchestrator → main → index.html → 验收

## T-1 — Git 初始化与基线提交（先于一切编码）
- [x] `git init`
- [ ] 提交基线：`git add docs/` → `git commit -m "docs: spec and skeleton task list baseline"`
- 原因：给后续 AI 编码代理留干净基线，便于用 `git diff` 像素级检查幻觉与越权改动

## T0 — 项目初始化
- [ ] 创建目录结构：`clients/`（空目录占位，Phase 0 不实现）、`assets/`（存储根）
- [ ] 写 `requirements.txt`：`fastapi`、`uvicorn[standard]`、`httpx`、`pydantic`、`python-multipart`（pillow 留到 Phase 2）
- [ ] 创建空的 `clients/__init__.py`（占位，便于 Phase 1+ 增量加文件）

## T1 — storage.py：存储抽象 + LocalAdapter
- [ ] 定义 `StorageBackend`（`typing.Protocol`）：
  - `async save(self, data: bytes, ext: str) -> str`  # 返回可访问 URL
  - `async download(self, url: str) -> bytes`  # 拉远程 URL 本地化
- [ ] 实现 `LocalAdapter(StorageBackend)`：
  - `__init__(self, root="assets", base_url="/assets")`
  - `save`：路径 `assets/{yyyy}/{mm}/{uuid}.{ext}`，`asyncio.to_thread` 写文件，返回 URL `{base_url}/{yyyy}/{mm}/{uuid}.{ext}`
  - `download`：`httpx.AsyncClient().get(url)` → 返回 `resp.content`
- [ ] 模块级单例 `storage = LocalAdapter()`
- [ ] 自测：`save(b"test","png")` 返回 URL，文件落盘

## T2 — orchestrator.py：编排引擎
- [ ] `TaskRegistry` 类（内存 dict，方法签名兼容未来 SQLite）：
  - `get(task_id) -> dict | None`
  - `set(task_id, record)` / `update(task_id, **fields)`（自动刷 `updated_at`）
  - `list_by_workflow(wf_id) -> list[dict]`
- [ ] 任务记录字段严格按 spec §5.1：`task_id, workflow_id, stage, status, progress, assets{character_png,poster_png,video_mp4}, error, created_at, updated_at`
- [ ] 全局 `SEM = asyncio.Semaphore(3)`
- [ ] `create_task(workflow_id, stage, params) -> str`：
  - 生成 uuid，注册 pending 记录
  - `asyncio.create_task(_run(task_id, stage, params))`（不 await）
  - 立即返回 task_id
- [ ] `_run(task_id, stage, params)`：`async with SEM:` → `update(status="running")` → 按 stage 分发到 `execute_*` → 成功设 success / 异常设 failed(error)
- [ ] `execute_mock(task_id)`：`for p in range(0,101,10)`：`update(progress=p)` + `await asyncio.sleep(0.5)`；结束设 `status="success"`
- [ ] **mock 完成后落占位资产**：`storage.save(_placeholder_png(), "png")` 写一个真实可访问的 1x1 PNG 到 `assets.character_png`，让前端拿到的 URL 真实可打开（支撑验收点 5）
- [ ] registry 全局单例 `registry = TaskRegistry()`

## T3 — main.py：FastAPI 路由
- [ ] `app = FastAPI()`
- [ ] 挂载静态资源：`app.mount("/assets", StaticFiles(directory="assets"), "assets")`
- [ ] `GET /` → `FileResponse("index.html")`（同源服务前端，免 CORS）
- [ ] Pydantic 入参模型：
  - `MockRunRequest(workflow_id: str)`
  - `AssetUploadResponse(url: str)`
  - `TaskStatusResponse(status, stage, progress, assets, error)`
- [ ] `POST /api/stages/mock/run`：调 `orchestrator.create_task(wf_id,"mock",{})` → 返回 `{"task_id"}`
- [ ] `GET /api/tasks/{task_id}`：`registry.get` → 返回 TaskStatusResponse（不存在 404）
- [ ] `POST /api/assets/upload`：接 `UploadFile`，读 bytes，按扩展名 `storage.save` → 返回 `{"url"}`
- [ ] 启动：`uvicorn main:app --reload --port 8000`

## T4 — index.html：多卡片并行前端
- [ ] 引入 Tailwind CDN、Fabric.js CDN（Fabric.js Phase 0 仅引入，画布区留占位）
- [ ] 左右分栏布局：左栏卡片轨、右栏画布占位
- [ ] `let workflows = []`；每元素 `{ id, mock_tid, status, progress }`
- [ ] `render()`：遍历 workflows 渲染卡片（状态文字 + 进度条 + 运行按钮 + 删除按钮）
- [ ] `[+新增流水线]`：`workflows.push({...})` → `render()`
- [ ] 删除卡片：splice + 清理该卡 `setInterval` + `render()`
- [ ] `runMock(wfId)`：POST `/api/stages/mock/run` `{workflow_id}` → 存 `mock_tid` → `pollTask(wfId, tid)`
- [ ] `pollTask(wfId, tid)`：`setInterval(1500)` GET `/api/tasks/{tid}` → 更新该卡 status/progress → `render()`；success/failed 时 `clearInterval` 停止
- [ ] **每张卡片独立定时器，互不影响**（核心验收点）
- [ ] 右栏画布占位：一个空 div + "Fabric.js 画布（Phase 2 接入）" 提示

## T5 — 验收验证（对应 spec §11 五条）
- [ ] 验收1：动态增删 N 张卡片，配置独立
- [ ] 验收2：同时点 3 张"运行"，各自进度条独立推进，互不阻塞
- [ ] 验收3：同时点 5 张，观察后端日志/状态——最多 3 个 running，其余 pending，完成一个放行一个
- [ ] 验收4：各卡独立到 success/failed，互不影响
- [ ] 验收5：上传一张图 → 拿到 url → 浏览器能打开该 url 看到图

## 依赖关系
T1 → T2（orchestrator 暂不依赖 storage，但 upload 依赖）→ T3（依赖 T1+T2）→ T4（依赖 T3 接口）→ T5

## 不在 Phase 0 做
clients/gpt_image.py、clients/seedance.py、clients/auth.py 真实实现；Fabric.js 画布实际功能；阶段二。
