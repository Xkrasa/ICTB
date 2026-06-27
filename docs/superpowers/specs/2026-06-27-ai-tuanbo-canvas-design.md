# AI 团播资产画布系统（多流并行版）— 设计规格

- 日期：2026-06-27
- 状态：已通过设计评审，待写实施计划
- 范围：MVP 单机单运营，并行多卡片工作流；后续将替换公司已有的串行海报生成流程

## 1. 项目目标

1. **交互重构**：淘汰 ComfyUI 式连线节点，降维为"卡片轨道（Track）+ 独立生命周期"。运营无须连线，配好参数即可在多张卡片上并行触发。
2. **渐进式资产链**：人物进化（发型/妆容/服装）→ 静态海报（背景 + 矢量文字）→ 动态视频，三阶段因果链。
3. **并行抽卡**：多条工作流独立、异步、并行执行，互不阻塞；并发上限可配置，防止 API 账单失控。
4. **AI 结对编程友好**：原生单文件前端（Tailwind CDN + Fabric.js CDN）+ FastAPI 后端，模块小而聚焦，便于 AI 代理准确写入。

## 2. 对原白皮书的修正

| # | 原方案 | 修正为 | 原因 |
|---|---|---|---|
| 1 | 阶段三：灰色遮罩盖脸 → 生成 → FFmpeg 切帧恢复脸 | 授权校验 → 上传人脸到 Seedance 资产库拿 `asset_id` → `seedance-2-less-restriction` 生成；未授权直接拦截不生成 | 遮罩方案技术不成立（遮罩贯穿全片，切帧恢复不了脸）且属绕审核；less-restriction 是官方合规正道，恰好对接已有 H5 扫脸授权 |
| 2 | 阶段一：自建 Face Embedding 缓存做锁脸 | 直接用 gpt-image-2 原生人脸一致性（参考图 + thinking mode） | gpt-image-2 换装/换背景保持同一人是其主打能力，无需自建人脸解析层 |
| 3 | 资产存储未提及 | 新增存储抽象层 `storage.py`（LocalAdapter 起步，接口预留 NAS/TOS） | 两个 API 都要图片 URL；seedance 视频链接 24h 过期需下载保存；后续接 NAS/TOS |
| 4 | 异步排队：FastAPI BackgroundTasks + 线程池 | asyncio 编排 + `asyncio.Semaphore` 并发闸 + 内存 TaskRegistry（SQLite 接口预留） | 10-20 路长轮询（seedance 单任务 2-15 分钟）线程池阻塞浪费；Semaphore 一行实现并发上限=成本/限流控制 |

## 3. 技术选型

| 模块 | 选型 | 说明 |
|---|---|---|
| 前端布局 | Tailwind CSS（CDN） | AI 类名编写准确率高，无样式冲突 |
| 海报图层 | Fabric.js（CDN） | 成熟 Canvas 库，AI 语料丰富；矢量文字防模型乱码 |
| 交互逻辑 | Vanilla JS（单文件 `index.html`） | 规避框架幻觉，`workflows[]` 数组数据驱动 |
| 后端底座 | FastAPI（Python） | 异步原生，Pydantic 类型校验，AI 写接口精准 |
| 异步编排 | asyncio + `asyncio.Semaphore(3)` | 长轮询真异步，并发闸卡死 API 并发上限 |
| 任务状态 | 内存字典 `TaskRegistry`（SQLite 接口预留） | MVP 轻量；进程重启丢失为已知限制 |
| 图像生成 | gpt-image-2（第三方 API 调用） | 原生 RGBA 透明 PNG + 人脸一致性 + thinking mode |
| 视频生成 | Seedance 2.0（官方火山引擎 Ark + 中转渠道切换） | 首帧/首尾帧/多模态参考；`less-restriction` 模式需资产库验证人脸 |
| 授权 | 对接已有 H5 扫脸授权系统 | 拿授权状态 + 人脸图，并支持上传到 Seedance 资产库 |

## 4. 系统架构总览

```
┌──────────────────────────── 前端 index.html ────────────────────────────┐
│  左栏：并发流水线卡片轨（workflows[]）            右栏：Fabric.js 画布     │
│  ┌─卡片1 [形象][海报][视频] 状态机+轮询┐         背景+人物背透+矢量文字     │
│  ├─卡片2 [形象][海报][视频] 状态机+轮询┤         导出海报图 → 上传 → 首帧  │
│  └─[+新增流水线]                       ┘                                  │
└──────────────────────────────────────────────────────────────────────────┘
                  │ POST /run (每阶段独立触发)        │ POST /assets/upload
                  │ GET /tasks/{id} 长轮询            │
                  ▼                                   ▼
┌──────────────────────── 后端 FastAPI ───────────────────────────────────┐
│  main.py  ── 路由 / 长轮询 / 静态文件                                      │
│  orchestrator.py ── asyncio 编排 + Semaphore(3) + TaskRegistry(内存)      │
│  storage.py ── 存储抽象（LocalAdapter，预留 NAS/TOS）                     │
│  clients/                                                                  │
│    gpt_image.py ── gpt-image-2 适配（第三方 API）                          │
│    seedance.py  ── seedance 2.0 适配（官方+中转渠道切换 + 资产库）         │
│    auth.py      ── 对接已有 H5 扫脸授权系统                                │
└──────────────────────────────────────────────────────────────────────────┘
                  │                                  │
                  ▼                                  ▼
        gpt-image-2（第三方）            Seedance 2.0（官方/中转）
```

**关键设计：阶段独立触发，非单一大任务。**
- 阶段一（形象加工）和阶段三（视频）是昂贵的 AI 调用，支持多卡片**批量并行**——这是"并行抽卡"的核心价值。
- 阶段二（海报拼装）是运营在右侧 Fabric.js 画布上的**交互式创作**，不属于并行批处理；导出海报图上传后作为阶段三首帧。
- 因此每张卡片按阶段分别触发后端任务，各自独立的 task_id 与状态机，互不阻塞。

## 5. 后端编排设计

### 5.1 TaskRegistry（内存，预留 SQLite）

位于 `orchestrator.py`。MVP 用 dict 实现，封装为 `TaskRegistry` 类，方法签名与 SQLite 实现兼容（`get`/`set`/`update`/`list_by_workflow`），后续可无缝替换。

任务记录结构：
```python
{
  "task_id": str,            # uuid
  "workflow_id": str,        # 前端卡片 id
  "stage": "character" | "video" | "mock",
  "status": "pending" | "running" | "success" | "failed",
  "progress": int,           # 0-100
  "assets": {                # 阶段产出的资产 URL
    "character_png": str | None,
    "poster_png": str | None,   # 阶段二由前端上传，非后端生成
    "video_mp4": str | None
  },
  "error": str | None,
  "created_at": float,
  "updated_at": float
}
```

### 5.2 并发闸

- 全局 `asyncio.Semaphore(3)`，所有阶段任务共享。MVP 设 3，后续按 API 配额调整。
- 任务流程：`create_task()` 注册 pending → `asyncio.create_task(run())` → `run()` 内 `async with SEM: await execute_stage()` → 更新状态。
- 不会因为某张卡片的长轮询阻塞其他卡片；超过并发上限的任务停在 pending，有空位即放行。

### 5.3 长轮询接口

前端每张卡片独立 `setInterval` 轮询 `GET /api/tasks/{task_id}`。后端直接返回当前状态（非 hold 连接），前端按 1.5s 间隔重试。各卡片定时器独立，互不影响。

## 6. 前端设计

### 6.1 数据驱动卡片

`let workflows = []`，每个元素描述一张卡片：`{ id, config: {character, poster, video}, tasks: {character_tid, video_tid}, status }`。增删卡片即数组操作 + 重渲染。

### 6.2 卡片状态机（独立生命周期）

每张卡片按阶段独立状态：
- 阶段一：`idle → running(progress) → success(character_png) | failed`
- 阶段二：前端交互，无后端任务；完成标志 = 海报图已导出上传
- 阶段三：`idle → running(progress) → success(video_mp4) | failed`

每阶段独立的轮询定时器，卡片互不阻塞。

### 6.3 右侧 Fabric.js 画布

- 只负责**静态海报分层拼装**：背景层 + 人物背透 PNG 层 + 矢量文字层（色块/边框/文字）。
- 左侧卡片任一阶段资产可"应用到画布"。
- 拼装完成导出海报图（PNG）→ `POST /api/assets/upload` → 得到 URL → 作为阶段三首帧。
- 视频不在画布回显，回到左侧卡片回显。

## 7. 三阶段业务闭环

### 阶段一：主播形象加工（Character Assemble）
- 输入：主播原图 URL（运营上传）+ 发型/妆容/服装配置
- 调用：`clients/gpt_image.py`，参考图 = 主播原图，prompt 描述换装，启用 thinking mode 锁五官
- 产出：高精背透 PNG（gpt-image-2 原生 RGBA），存 storage，URL 入 task assets
- 人脸一致性由 gpt-image-2 原生能力保证，不建人脸解析层

### 阶段二：静态海报组装（Poster Composition）
- 在前端 Fabric.js 画布交互完成：背景图 + 阶段一人物背透 + 矢量文字/色块/边框
- 文字为矢量图层，不经过模型，100% 不乱码
- 导出海报 PNG → 上传后端 → 得 poster_png URL
- 此阶段无后端 AI 任务

### 阶段三：动态视频生成（Video Engine）
- 前置：`clients/auth.py` 校验该主播授权状态
  - 未授权 → 拦截，卡片报错"主播未授权"，不生成
  - 已授权 → 取人脸图，上传到 Seedance 私有资产库拿 `asset_id`（首次上传后缓存 asset_id，复用）
- 调用：`clients/seedance.py`，`seedance-2-less-restriction` 模式，首帧 = 海报 PNG URL，prompt 描述镜头运动
- 异步：POST 创建 → requestId → 轮询直到 SUCCESS
- 后处理：视频 URL 24h 过期，下载保存到 storage，返回永久 URL，入 task assets
- **不实现遮罩 hack**：合规正道，授权后走 less-restriction

## 8. 存储抽象（storage.py）

```python
class StorageBackend(Protocol):
    async def save(self, data: bytes, ext: str) -> str: ...   # 返回可访问 URL
    async def download(self, url: str) -> bytes: ...           # 拉取远程 URL 本地化

class LocalAdapter:   # MVP：本地磁盘 + FastAPI StaticFiles
    ...
# 后续：class NASAdapter / TOSAdapter，实现同接口
```
- 路径：`assets/{yyyy}/{mm}/{uuid}.{ext}`
- 对外通过 FastAPI StaticFiles 暴露为 URL，供 gpt-image-2 参考图、seedance mediaUrls 使用
- seedance 视频 URL 过期前由 `download()` 拉回本地保存

## 9. API 设计

| 方法 | 路径 | 说明 | 返回 |
|---|---|---|---|
| POST | `/api/assets/upload` | 上传图片（主播原图/背景图/海报导出图） | `{ url }`（url 即后续引用凭据） |
| POST | `/api/stages/character/run` | 触发阶段一。body: `{ workflow_id, reference_image_url, hair, makeup, clothing }` | `{ task_id }` |
| POST | `/api/stages/video/run` | 触发阶段三。body: `{ workflow_id, poster_image_url, streamer_id }` | `{ task_id }` |
| GET | `/api/tasks/{task_id}` | 轮询任务状态 | `{ status, stage, progress, assets, error }` |
| GET | `/assets/{path}` | 静态资源服务 | 文件 |

- 阶段二无后端任务（前端 Fabric.js 完成）
- 所有 `/run` 接口秒回 task_id，不阻塞
- Pydantic 模型校验入参

## 10. 模块/文件结构

```
Poster_tuanbo/
  index.html              # 单文件前端：Tailwind CDN + Fabric.js CDN + workflows[]
  main.py                 # FastAPI 入口、路由、长轮询、静态文件挂载
  orchestrator.py         # asyncio 编排 + Semaphore(3) + TaskRegistry(内存/SQLite 接口)
  storage.py              # 存储抽象：LocalAdapter（预留 NAS/TOS）
  clients/
    gpt_image.py          # gpt-image-2 适配（第三方 API）
    seedance.py           # seedance 2.0 适配（官方+中转渠道切换 + 资产库上传）
    auth.py               # 对接已有 H5 扫脸授权系统
  assets/                 # 本地存储根目录
  requirements.txt        # fastapi, uvicorn, httpx, pydantic, pillow
```

## 11. Phase 0 骨架设计与验收标准

**目标**：先验证并行架构本身，业务阶段全部用 mock。

**实现范围**：
- `index.html`：多卡片框架，`[+新增流水线]` 动态加卡，每卡有"运行 mock 阶段"按钮、独立进度条、独立状态
- `main.py`：`/api/stages/mock/run`、`/api/tasks/{id}`、`/api/assets/upload`、静态文件挂载
- `orchestrator.py`：`TaskRegistry`（内存）、`Semaphore(3)`、mock 任务协程（await 信号量 → 每 0.5s 推进 progress 0→100 共约 5s → success）
- `storage.py`：`LocalAdapter` 基本实现（save/download）

**验收标准**：
1. 能动态增删 N 张卡片，各自配置独立
2. 同时点击多张卡片"运行"，各自独立进度条推进，互不阻塞
3. 并发闸生效：同时触发 5 张，最多 3 个 running，其余 pending，完成一个放行一个
4. 每张卡片独立轮询、独立完成/失败状态，不互相影响
5. 上传图片能存本地并通过 URL 访问

**不在 Phase 0 做**：gpt-image-2 / seedance / auth 真实接入、Fabric.js 画布、阶段二。

## 12. Phase 1-3 业务阶段计划

- **Phase 1**：接入 `clients/gpt_image.py`，实现阶段一真实换装 + 背透 PNG 产出。替换 Phase 0 的 mock。
- **Phase 2**：实现右侧 Fabric.js 画布（背景/人物/矢量文字分层 + 导出上传），打通"阶段一资产 → 画布 → 海报 URL"。
- **Phase 3**：接入 `clients/auth.py` + `clients/seedance.py`，实现授权校验 + 资产库上传拿 asset_id + less-restriction 视频生成 + 视频下载保存。

每阶段在 Phase 0 骨架上增量替换，不推翻架构。

## 13. 已知限制与预留接口

- **进程重启丢失任务状态**：MVP 接受。`TaskRegistry` 接口预留 SQLite 实现，后续可落盘恢复。
- **单机单运营**：MVP 不做 Web 层鉴权/多租户。后续多运营需加用户体系。
- **并发上限 3**：MVP 值，按 API 配额调整 `Semaphore` 参数即可。
- **存储本地**：`StorageBackend` 接口预留 NAS/TOS，替换 `LocalAdapter` 即可，业务层无感。
- **Seedance 渠道切换**：`clients/seedance.py` 内置官方/中转多渠道配置，按可用性/成本切换。
