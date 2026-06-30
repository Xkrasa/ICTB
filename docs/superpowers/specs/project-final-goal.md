# AI 团播资产画布系统 — 项目最终目标

- 日期：2026-06-30
- 状态：MVP 已完成并通过验收，处于可内部上线状态

## 1. 产品定位

为团播运营提供一套**模板化批量生产主播素材**的工具：一套换装模板套到一批主播身上，每主播并行生成 N 张候选图，运营单选采用后一键出动态视频。

核心心智：**选主播 → 选模板 → 批量生成候选 → 单选采用 → 出片**，而非"连节点"。

## 2. 核心目标

1. **批量并行抽卡**：M 个主播 × N 张候选并行生成，互不阻塞；并发闸严格控成本（`Semaphore(3)` 硬约束）。
2. **模板复用**：画布链路存为模板，一键克隆到任意主播集合，复用完整上游 DAG（image_input → remove_bg → gpt_image）。
3. **多模型生图**：AI 生图节点统一为单节点 + 模型下拉（gpt-image-2 / rh_gpt_image_i2i / nano_banana_pro / nano_banana_2），历史独立节点类型自动迁移。
4. **人工断点采用**：候选采用为人工决策点，采用后再触发视频生成二次 canvas run，不自动级联。
5. **可内部上线**：API Key 访问控制、文件上传校验、健康检查、日志、任务状态快照恢复、路由顺序修正等加固项全部落地。

## 3. 业务闭环

```
模板库 ──┐
         ├─→ 批量编排（每主播克隆上游 DAG + N 候选并行）
主播库 ──┘         │
                   ↓
            候选网格（2s 单接口轮询聚合）
                   │
                   ↓
            人工采用（单选，可覆盖）
                   │
                   ↓
            视频生成（phase2 canvas: adopted_image → seedance_video）
                   │
                   ↓
            视频下载转存（RH URL 24h 过期 → 本地永久 URL）
```

## 4. 技术架构

- **后端**：FastAPI + asyncio + Semaphore(3) + 内存 TaskRegistry（JSON 快照恢复，SQLite 接口预留）
- **前端**：Vanilla JS + Tailwind，运营模式（默认）+ 高级画布模式双视图
- **存储**：LocalAdapter（`assets/{yyyy}/{mm}/{uuid}.{ext}`），NAS/TOS 接口预留
- **AI 渠道**：gpt-image-2（同步 + xhub failover）、RunningHub（seedance 视频 + RH 工作流生图 + remove_bg 抠图）

## 5. 当前状态

- Phase 0-4 + 试生产加固 + AI 生图节点模型合并：**全部完成**
- 端到端测试套件 [tests/test_e2e.py](../../tests/test_e2e.py) 覆盖 9 大模块
- 验收结论：核心 P0/P1 问题已全部修复，工程质量已达可内部上线水平

## 6. 未达成的演进项（非 MVP 必需）

- SQLite 持久化替换内存 dict（接口已预留）
- NAS/TOS 存储适配（`StorageBackend` Protocol 已预留）
- 多租户 Web 层鉴权
- `BATCH_CONCURRENCY` 独立信号量（当前批量共享全局 SEM=3）
- 候选雷同 prompt variation
- 前端视频预览渲染（当前 seedance_video 节点显示首帧图，非视频）
- RunningHub 任务重启后续跑

## 7. 项目硬约束（不可违反）

- 后端必须 asyncio 编排 + Semaphore 并发控制
- 任务状态内存字典 + SQLite 接口预留
- 前端卡片/节点独立状态机 + setInterval 轮询
- 存储路径含动态日期目录
- 图像处理强制 RGBA 转换防 Alpha 丢失
- gpt-image-2 用 'gpt-image-2' 模型名（非 -all 变体）
- API 错误指数退避重试（429/5xx，5s/10s/20s，最多 3 次）
- llm-api.net 与 xhub/newapi.pro 互为 failover
- UI 无 emoji，用 SVG 图标或文字
- 文件上传 20MB 限制 + MIME 白名单
- 路由顺序：`/api/batch/list` 必须在 `/api/batch/{batch_id}` 之前
