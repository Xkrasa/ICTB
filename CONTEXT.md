# 项目领域词汇与架构模块（CONTEXT.md）

> 架构评审深化后建立。后续开发用这些术语指代模块与概念，避免漂移。

## 领域词汇（业务）

| 术语 | 含义 |
|---|---|
| 画布（Canvas） | 节点 DAG 工作流，存为 JSON（canvases/）或模板（templates/） |
| 节点（Node） | 画布上的处理单元，5 种类型：image_input / gpt_image / remove_bg / mask_edit / seedance_video |
| 候选（Candidate） | 批量生产中每主播并行生成的 N 张图，人工单选采用 |
| 采用（Adopt） | 人工断点：从候选中选定一张，作为视频生成的首帧 |
| 主播（Streamer） | 批量生产的目标人物（streamers/），含原图 URL |
| 模板（Template） | 可复用的画布链路（templates/），批量克隆到主播集合 |
| 批次（Batch） | 一次批量生产的运行实例（batches/），含多主播×多候选 |

## 架构模块（深化后）

### 后端

| 模块 | 文件 | 职责 | 接口 |
|---|---|---|---|
| **node_types** | node_types.py | 节点类型定义 | NodeInput dataclass×5、NodeOutput、NODE_PORTS（含 overridable）、build_input |
| **PortResolver** | port_resolver.py | 上游注入 + 字段归一化 | resolve(node, upstream_recs, conns) → NodeInput（纯函数） |
| **executors** | executors/ | 5 个节点执行器（纯函数） | execute(input, on_progress, on_submitted) → NodeOutput |
| **registry** | orchestrator/registry.py | TaskRegistry：SQLite 持久化 + 内存缓存 + 域查询 | get/set/update + find_canvas_image_url/get_canvas_nodes |
| **engine** | orchestrator/engine.py | DAG 级联引擎 | execute_canvas / _run_node / _schedule_cascade / approve_node / reject_node |
| **phase1** | orchestrator/phase1.py | 旧单任务 API 兼容 | create_task / execute_mock / execute_character |
| **batch** | orchestrator/batch.py | 批量编排 | execute_batch / aggregate_batch / adopt_batch / retry_candidate / start_video |
| **_shared** | orchestrator/_shared.py | 跨模块共享 | SEM / _background_tasks / classify_error / _record_image_size / ERROR_CODES |

### 依赖图（无循环）

```
registry → (无)
_shared → registry
phase1 → _shared + registry
engine → _shared + registry + node_types + port_resolver + executors
batch → registry + engine + storage
```

### 前端

| 模块 | 文件 | 职责 |
|---|---|---|
| state | static/js/state.js | 全局变量 + NODE_PORTS 常量 + TuanboApp 骨架 |
| api | static/js/api.js | _apiHeaders / _apiFetch |
| canvas | static/js/canvas.js | 画布模式（节点/连线/端口/遮罩/运行/轮询） |
| ops | static/js/ops.js | 运营生产台（主播/模板/批量/采用/视频） |
| project | static/js/project.js | 项目抽屉与画布列表 |
| init | static/js/init.js | 自动平铺 + 状态栏 + 初始化 |

## 关键设计决策

1. **执行器是纯函数**：`execute(input, on_progress, on_submitted) → NodeOutput`，不碰 registry/_canvas_contexts。引擎负责写 registry。测试喂 NodeInput + mock.patch(storage)。
2. **PortResolver 统一注入+归一化**：原 4 个分散函数集中到一个纯函数。NODE_PORTS 从文档变为执行依据。
3. **_OVERRIDABLE 移入 NODE_PORTS**：每个节点类型声明 overridable，消除两处重复硬编码。
4. **orchestrator 包**：1089 行单文件拆为 6 文件包，main.py 通过 __init__.py re-export 零改动。
5. **TaskRegistry 持久化层/查询层分界**：注释明确分界，未提取 CanvasQuery（2 方法各 1 调用点，提取会变浅模块）。

## 不做的事（ADR 候选）

- **不提取 CanvasQuery 类**：候选 4 评估后，2 个活跃查询方法各只 1 调用点，提取会创造浅模块。保留在 TaskRegistry + 注释分界。若未来存储换 NAS/TOS 或查询增至 5+ 个，再提取。
- **不重写前端为 ES module**：80+ onclick 函数需全局可见，ES module 需手动 window 导出易漏。用全局命名空间 + Object.assign 挂载 + 自动平铺。
- **不引入 WebSocket**：800ms 轮询聚合后单机撑得住，WebSocket 断线重连复杂度不值。
