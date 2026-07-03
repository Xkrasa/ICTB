# 画布工作流优化研究报告

> 基于对 ComfyUI、Coze、Dify、n8n 四大成熟平台的研究，结合当前项目代码审查，整理出可落地的优化建议。
>
> 日期：2026-07-02

---

## 一、当前项目现状速览

### 1.1 技术栈与规模

| 层 | 技术 | 核心文件 | 行数 | 问题 |
|---|---|---|---|---|
| 后端 | FastAPI + asyncio | `orchestrator.py` | 1063 | 单文件承载 Phase 1-4 全部逻辑 |
| 后端入口 | FastAPI | `main.py` | 478 | 25 个路由，路由顺序敏感 |
| 客户端 | httpx | `clients/*.py` | ~820 | 每次请求新建 AsyncClient |
| 前端 | Vanilla JS 单文件 | `static/app.js` | 1997 | 84 个函数挤在一个文件，无模块化 |
| 前端样式 | CSS | `static/styles.css` | 683 | 单文件 |
| 持久化 | SQLite + JSON 文件 | `runtime/tasks.db` | - | 每次写盘新建连接 |

### 1.2 节点系统现状

5 种节点类型：`image_input` / `gpt_image` / `remove_bg` / `mask_edit` / `seedance_video`

**端口模型**（关键限制）：
- 每个非 image_input 节点只有 **1 个输入端口**
- 所有节点只有 **1 个输出端口**
- 连线数据结构 `{id, from, to}` **无端口索引**
- 多参考图输入靠 `image2_url` / `image3_url` / `hair_url` / `clothing_url` 等**约定字段名**实现，无端口语义

**变量传递**：
- 固定字段名写死在前后端（`image_url` / `mask_url` / `video_url`）
- `_OVERRIDABLE` 集合硬编码节点类型（`orchestrator.py` L497）
- 新增节点类型需改前后端多处

### 1.3 执行引擎现状

- DAG 拓扑排序 + 级联执行（`_schedule_cascade`）
- `Semaphore(3)` 全局并发闸
- 上游产出注入下游有两条路径：后端级联注入 + 前端预填
- 无缓存机制，每次运行全量重算
- 无节点级错误重试策略
- `_canvas_contexts` 纯内存，重启即失

### 1.4 主要痛点

1. **app.js 单文件 1997 行**，维护困难
2. **端口模型不支持显式多输入**，"图1/图2"靠字段名约定
3. **无变量系统**，字段名硬编码
4. **错误处理不完善**，多处 `except Exception` 吞异常
5. **无调试能力**，无节点级日志面板、无运行历史回放
6. **测试覆盖不足**，仅 2 个测试文件
7. **性能瓶颈**：SQLite 无连接池、前端 N 路轮询、SVG 全量重建
8. **多上游处理薄弱**，只取第一个有 URL 的上游

---

## 二、四大平台设计精华

### 2.1 ComfyUI — 节点引擎标杆

| 设计 | 精华 | 借鉴价值 |
|---|---|---|
| **类型系统** | 字符串常量（`"IMAGE"`/`"MASK"`/`"TEXT"`）+ 端口颜色编码（IMAGE=蓝、MASK=绿、MODEL=紫） | ★★★★★ 直接照搬 |
| **双 JSON 格式** | UI 格式（含坐标/size/groups）与 API 格式（扁平依赖）分离 | ★★★★★ 编辑态/执行态分离 |
| **祖先签名缓存** | `HierarchicalCache` 哈希节点整条祖先链，上游没变直接命中缓存 | ★★★★☆ 增量渲染关键 |
| **节点 Bypass/Mute** | `node.mode` 字段：0=active, 1=mute, 2=bypass（透传输入到输出） | ★★★★☆ A/B 对比调试 |
| **复制粘贴双语义** | `Ctrl+C/V` 不保留未选中节点连线，`Ctrl+Shift+V` 保留 | ★★★★☆ 直接照搬 |
| **双击搜索添加** | 双击空白弹出节点搜索框，关键词匹配 | ★★★★☆ UX 优化 |
| **Ctrl+G 分组** | 分组带标题/颜色/bounding box，可锁定 | ★★★☆☆ 画布组织 |
| **WebSocket 事件** | `execution_start`/`progress`/`executing`/`executed` 实时推送 | ★★★★★ 替代轮询 |
| **Reroute 节点** | 纯走线整理节点，无逻辑 | ★★★☆☆ 画布整洁 |
| **子图 Blueprint** | 一组节点打包成新节点，可复用 | ★★★☆☆ 模板组件化 |
| **PNG 元数据嵌入** | 导出图片含完整 workflow JSON，拖回画布复现 | ★★☆☆☆ 特色功能 |

### 2.2 Dify — 最契合本项目的参考

| 设计 | 精华 | 借鉴价值 |
|---|---|---|
| **语义化输出端口** | source handle 区分：`source`/`true`/`false`/`success-branch`/`fail-branch`/`loop` | ★★★★★ 失败分支降级 |
| **中央 VariablePool** | `{node_id: {field: typed_value}}`，类型严格匹配，引用语法 `{{#node.field#}}` | ★★★★★ 替代字段名约定 |
| **Last Run Tracking** | 持久化每个节点上次执行的输入/输出/元数据（飞行记录仪） | ★★★★★ 调试核心 |
| **Variable Inspect 面板** | 画布底部常驻，实时显示全部变量并支持直接编辑 | ★★★★★ 调试体验 |
| **单节点 Step-Run** | 选中节点点击运行，自动拉取依赖数据，不重跑上游 | ★★★★★ 省钱省时 |
| **错误三策略** | `None`（中断）/ `Default Value`（默认值）/ `Fail Branch`（失败分支） | ★★★★☆ 灵活容错 |
| **Retry on Failure** | 最大次数 + 间隔 + 指数退避，节点级配置 | ★★★★☆ 替代全局退避 |
| **Token/延迟监控** | 每节点显示 Token 消耗和执行耗时 | ★★★☆☆ 成本可观测 |

### 2.3 Coze — AI 节点配置体验参考

| 设计 | 精华 | 借鉴价值 |
|---|---|---|
| **右侧配置侧边栏** | 统一管理参数/Prompt/模型/输出格式 | ★★★★☆ 替代节点内嵌参数 |
| **JSON 样例生成结构** | 粘贴期望 JSON 样例，自动生成输出字段 schema | ★★★☆☆ AI 节点输出 |
| **LLM 技能挂载** | LLM 节点内挂载插件/工作流/知识库，Function Call 调用 | ★★☆☆☆ 过于复杂 |
| **版本管理与回滚** | 工作流发布版本，支持回滚 | ★★★☆☆ 模板版本 |
| **循环节点作用域隔离** | 循环体内外画布隔离，体内可引用体外全局变量 | ★★★☆☆ 批量处理 |

### 2.4 n8n — 数据流与表达式参考

| 设计 | 精华 | 借鉴价值 |
|---|---|---|
| **item 数组数据模型** | 一切数据都是 `[{json: {...}}]` 数组，天然批处理 | ★★★★☆ 批量出图 |
| **表达式编辑器** | 参数级切换"固定值/表达式"，变量选择器 + 即时预览 | ★★★☆☆ 高级用户 |
| **多输入多输出** | 节点可同时接收多条上游，按 true/false/success/error 多端口输出 | ★★☆☆☆ 过于自由 |
| **Error Workflow** | 失败时挂载独立错误处理工作流（发通知/记录日志） | ★★★☆☆ 运维解耦 |
| **数据面板三视图** | JSON / 表格 / Schema 三种视图查看节点输入输出 | ★★★★☆ 调试体验 |

---

## 三、对比分析：当前项目 vs 成熟平台

### 3.1 核心能力差距矩阵

| 能力 | 当前项目 | ComfyUI | Dify | Coze | n8n | 差距 |
|---|---|---|---|---|---|---|
| 端口类型系统 | 无（字段名约定） | 字符串常量+颜色 | 类型化 VariablePool | 强类型 | 弱类型 | **大** |
| 多输入支持 | 单 port-in + 字段约定 | 多端口+类型检查 | 单输入+变量映射 | 单输入+引用 | 多输入多输出 | **大** |
| 变量系统 | 无（固定字段名） | 无（端口直连） | 中央 VariablePool | `{{}}` 引用 | 表达式 `{{$json}}` | **大** |
| 错误处理 | 全局 except | 异常广播 | 三策略+Retry | 忽略+默认值 | 三模式+Error Workflow | **大** |
| 缓存机制 | 无 | 祖先签名缓存 | Last Run | 无 | 无 | **大** |
| 调试能力 | 无 | 实时高亮+WebSocket | Last Run+Variable Inspect | 全量试运行 | 单步+数据面板 | **大** |
| 实时通信 | 800ms 轮询 | WebSocket | SSE | 轮询 | 轮询 | 中 |
| 批量处理 | Phase 4 批量编排 | 无 | Loop/Iteration | Loop/Batch | item 数组 | 中 |
| 子工作流 | 无 | Subgraph Blueprint | 无 | 子工作流 | Sub-workflow | 中 |
| 代码结构 | 单文件巨石 | 模块化 | 模块化 | 模块化 | 模块化 | **大** |
| 测试覆盖 | 2 文件 | 充分 | 充分 | - | 充分 | **大** |

### 3.2 端口模型对比

**当前项目**：
```
[上游节点] ──→ [下游节点.唯一port-in]
                   └─ data.image_url / data.image2_url / data.hair_url（字段约定）
```

**ComfyUI**：
```
[CheckpointLoader] ──MODEL──→ [KSampler.MODEL]
                     ──CLIP──→ [CLIPTextEncode.CLIP]
                     ──VAE──→ [VAEDecode.VAE]
类型不匹配 → 拖线瞬间拦截，连不上
```

**Dify**：
```
[LLM节点] ──source──→ [下游节点]
           ──success-branch──→ [正常路径]
           ──fail-branch──→ [降级路径]
```

**结论**：当前项目的"单 port-in + 字段约定"是最弱的设计，应优先重构为 ComfyUI 式的多端口+类型系统。

### 3.3 变量传递对比

**当前项目**：
```python
# orchestrator.py 硬编码
ref_url = params.get("image_url")        # 主图
mask_url = params.get("mask_url")        # 遮罩
hair_url = params.get("hair_url")        # 发型图
clothing_url = params.get("clothing_url") # 服装图
```

**Dify VariablePool**：
```python
# 中央变量池，类型化
variable_pool = {
    "node_abc": {
        "output": {"image_url": "file://...", "width": 1024},
        "status": "success",
        "elapsed_ms": 3500
    }
}
# 下游节点通过 UI 选择引用上游字段，类型严格匹配
```

**结论**：应引入 Dify 式 VariablePool，替代字段名约定。

---

## 四、优化建议（按优先级分层）

### P0：架构基础重构（阻塞后续所有优化）

#### P0-1 前端模块化拆分

**现状**：`app.js` 1997 行 / 103KB / 84 函数挤在一个文件，无 ES module。

**目标**：拆分为 ES module，按职责分文件。

**建议结构**：
```
static/
├── app.js              # 入口，仅负责初始化
├── core/
│   ├── state.js        # canvasData / nodeRuntime / viewState
│   ├── api.js          # _apiFetch / _apiHeaders
│   └── history.js      # 撤销重做栈
├── canvas/
│   ├── viewport.js     # 视口变换 / 缩放 / 平移
│   ├── render.js       # renderNode / renderConnections
│   ├── interaction.js  # 拖拽 / 框选 / 连线
│   └── minimap.js      # 小地图
├── nodes/
│   ├── registry.js     # 节点类型注册
│   ├── image_input.js
│   ├── gpt_image.js
│   ├── mask_edit.js
│   ├── remove_bg.js
│   └── seedance_video.js
├── panels/
│   ├── toolbar.js
│   ├── sidepanel.js
│   ├── mask-editor.js
│   └── lightbox.js
└── utils/
    ├── dom.js
    └── format.js
```

**迁移策略**：用 ES module `<script type="module">` 引入，逐步迁移，保持功能不变。

---

#### P0-2 后端模块化拆分

**现状**：`orchestrator.py` 1063 行承载执行器 + 注册表 + 批量 + 级联。

**建议结构**：
```
orchestrator/
├── __init__.py         # 对外暴露 execute_canvas / create_task
├── registry.py         # TaskRegistry（SQLite 持久化）
├── engine.py           # DAG 解析 / 级联调度 / _start_node
├── executors/
│   ├── __init__.py     # _NODE_EXECUTORS 注册表
│   ├── image_input.py
│   ├── gpt_image.py
│   ├── mask_edit.py
│   ├── remove_bg.py
│   └── seedance_video.py
├── cache.py            # 节点输出缓存（P1 引入）
├── variables.py        # VariablePool（P1 引入）
└── batch.py            # Phase 4 批量编排
```

---

#### P0-3 端口模型重构

**现状**：单 port-in + 字段名约定，多输入靠 `image2_url` 等硬编码。

**目标**：借鉴 ComfyUI，引入多端口 + 类型系统。

**数据结构变更**：
```javascript
// 连线从 {id, from, to} 变为
{
  id: "xxx",
  from: { node: "abc", port: 0 },   // 输出端口索引
  to:   { node: "def", port: 1 }    // 输入端口索引
}

// 节点定义端口
const NODE_PORTS = {
  gpt_image: {
    inputs: [
      { name: "主体图", type: "IMAGE", required: false },
      { name: "发型图", type: "IMAGE", required: false },
      { name: "服装图", type: "IMAGE", required: false }
    ],
    outputs: [
      { name: "生成图", type: "IMAGE" }
    ]
  },
  mask_edit: {
    inputs: [
      { name: "原图", type: "IMAGE", required: true }
    ],
    outputs: [
      { name: "原图", type: "IMAGE" },
      { name: "遮罩", type: "MASK" }
    ]
  },
  seedance_video: {
    inputs: [
      { name: "首帧", type: "IMAGE", required: true },
      { name: "尾帧", type: "IMAGE", required: false }
    ],
    outputs: [
      { name: "视频", type: "VIDEO" }
    ]
  }
};

// 类型 → 颜色映射（ComfyUI 风格）
const TYPE_COLORS = {
  IMAGE: '#3B82F6',   // 蓝
  MASK:  '#10B981',   // 绿
  VIDEO: '#8B5CF6',   // 紫
  TEXT:  '#F59E0B'    // 橙
};
```

**类型检查**：拖线瞬间检查 `from.port.type === to.port.type`，不匹配拒绝连接，端口颜色不同即视觉提示。

**迁移策略**：旧连线 `{from, to}` 自动映射为 `{from: {node: from, port: 0}, to: {node: to, port: 0}}`，兼容旧数据。

---

### P1：核心能力提升

#### P1-1 引入 VariablePool（借鉴 Dify）

**现状**：`image_url` / `mask_url` 等字段名硬编码在前后端。

**目标**：中央变量池，节点输出自动注册，下游通过 UI 选择引用。

**后端实现**：
```python
class VariablePool:
    def __init__(self):
        self._vars: dict[str, dict[str, Any]] = {}  # {node_id: {field: value}}

    def set(self, node_id: str, **outputs):
        self._vars.setdefault(node_id, {}).update(outputs)

    def get(self, node_id: str, field: str, default=None):
        return self._vars.get(node_id, {}).get(field, default)

    def resolve(self, node_id: str, port_index: int, port_type: str) -> Any:
        """根据端口类型自动查找上游匹配的输出"""
        # 遍历连入该端口的连线，找到上游 node_id
        # 返回上游 node 对应类型的输出
```

**前端实现**：节点配置时，每个参数字段可选择"手动输入"或"引用上游输出"，引用时下拉选择已连线的上游节点及其输出字段。

---

#### P1-2 节点输出缓存（借鉴 ComfyUI）

**现状**：每次运行全量重算，AI 生图节点重复执行浪费成本。

**目标**：节点输出缓存，输入签名不变则命中缓存。

**实现**：
```python
class NodeCache:
    def __init__(self):
        self._cache: dict[str, tuple] = {}  # {cache_key: (output, timestamp)}

    def _signature(self, node_id: str, node_type: str, params: dict, upstream_sigs: list) -> str:
        """哈希节点参数 + 上游签名链"""
        import hashlib, json
        payload = json.dumps({
            "node_id": node_id,
            "node_type": node_type,
            "params": _sortable(params),
            "upstream": upstream_sigs
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def get(self, cache_key: str):
        return self._cache.get(cache_key)

    def set(self, cache_key: str, output: dict):
        self._cache[cache_key] = output
```

**缓存策略**：
- AI 生图节点：缓存 24 小时（输入签名 = prompt + model + size + 上游图片哈希）
- 抠图节点：缓存 7 天（输入签名 = 上游图片哈希）
- 遮罩编辑：不缓存（用户可能修改遮罩）
- 视频生成：缓存 1 小时（成本高，但输出大）

**手动清除**：节点右键菜单加"清除缓存"选项，`node.data._cache_busted = true` 强制重算。

---

#### P1-3 错误处理三策略（借鉴 Dify）

**现状**：全局 `except Exception`，节点失败直接阻断下游。

**目标**：每个节点可配置错误策略。

**节点 data 新增字段**：
```python
node.data.error_strategy = "none"           # 中断（默认）
node.data.error_strategy = "default_value"  # 使用默认值继续
node.data.error_strategy = "fail_branch"    # 走失败分支
node.data.retry = {"max": 3, "interval": 5, "backoff": "exponential"}
node.data.default_value = {"image_url": "file://placeholder.png"}
```

**执行器改造**：
```python
async def _run_node(canvas_id, node_id, task_id, node_type, params):
    retry_cfg = params.get("retry", {})
    max_attempts = retry_cfg.get("max", 1)
    for attempt in range(max_attempts):
        try:
            async with SEM:
                await _NODE_EXECUTORS[node_type](canvas_id, node_id, params)
            registry.update(f"{canvas_id}:{node_id}", status="success")
            _schedule_cascade(canvas_id, node_id, success=True)
            return
        except Exception as e:
            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_cfg.get("interval", 5) * (2 ** attempt))
                continue
            # 重试耗尽，按策略处理
            _handle_node_error(canvas_id, node_id, e, params)
```

---

#### P1-4 实时通信：WebSocket 替代轮询（借鉴 ComfyUI）

**现状**：每节点 800ms 轮询，10 节点 = 12.5 req/s。

**目标**：WebSocket 实时推送节点状态变更。

**后端**：
```python
from fastapi import WebSocket

@app.websocket("/ws/canvas/{canvas_id}")
async def canvas_ws(ws: WebSocket, canvas_id: str):
    await ws.accept()
    # 注册到 registry 的监听列表
    registry.add_listener(canvas_id, ws)
    try:
        while True:
            await ws.receive_text()  # 心跳
    except WebSocketDisconnect:
        registry.remove_listener(canvas_id, ws)

# TaskRegistry.update 时广播
def update(self, task_id, **fields):
    rec = ...
    if self._should_persist(task_id, rec, fields):
        self._persist(task_id, rec)
    # 广播给 WebSocket 监听者
    for ws in self._listeners.get(canvas_id, []):
        asyncio.create_task(ws.send_json({"node_id": ..., "status": ..., "progress": ...}))
```

**前端**：
```javascript
const ws = new WebSocket(`ws://${location.host}/ws/canvas/${currentCanvasId}`);
ws.onmessage = (e) => {
    const d = JSON.parse(e.data);
    updateNodeUI(d.node_id, d);
    if (['success','failed','blocked'].includes(d.status)) {
        checkAllDone();
    }
};
// 不再需要 startPolling / stopPolling
```

---

### P2：调试与可观测性

#### P2-1 Last Run Tracking（借鉴 Dify）

**目标**：持久化每个节点上次执行的输入/输出/元数据。

**实现**：
```python
# TaskRegistry 新增 last_run 字段
def _new_node_record(canvas_id, node_id, node_type):
    return {
        ...,
        "last_run": {
            "inputs": None,      # 上次执行的 params 快照
            "outputs": None,     # 上次执行的产出（image_url 等）
            "error": None,
            "elapsed_ms": None,
            "started_at": None,
            "finished_at": None,
            "token_cost": None,  # AI 节点的 Token 消耗
        }
    }
```

**前端**：节点右键菜单加"查看上次运行"，弹出面板显示输入/输出/耗时/错误。

---

#### P2-2 Variable Inspect 面板（借鉴 Dify）

**目标**：画布底部常驻变量检查面板，实时显示所有节点状态和产出。

**UI 设计**：
```
┌─────────────────────────────────────────────────────────┐
│ 画布区域                                                  │
│                                                          │
├─────────────────────────────────────────────────────────┤
│ 变量检查器（可折叠）                                       │
│ ┌──────────┬──────────┬──────────┬──────────┬─────────┐│
│ │ 节点      │ 状态     │ 输入     │ 输出     │ 耗时    ││
│ ├──────────┼──────────┼──────────┼──────────┼─────────┤│
│ │ AI生图   │ success  │ ref.png  │ out.png  │ 3.2s    ││
│ │ 抠图     │ running  │ out.png  │ -        │ 1.1s    ││
│ └──────────┴──────────┴──────────┴──────────┴─────────┘│
└─────────────────────────────────────────────────────────┘
```

---

#### P2-3 单节点 Step-Run（借鉴 Dify）

**目标**：选中节点点击运行，自动拉取上次成功的上游数据，不重跑上游。

**实现**：
```javascript
async function stepRunNode(nodeId) {
    const node = canvasData.nodes.find(n => n.id === nodeId);
    // 从 Last Run 拉取上游产出
    for (const c of canvasData.connections.filter(c => c.to === nodeId)) {
        const upstream = nodeRuntime[c.from];
        if (upstream?.status === 'success' && upstream.image_url) {
            node.data.image_url = upstream.image_url;
        }
    }
    // 只运行这一个节点
    runCanvas([nodeId]);
}
```

**UI**：节点悬停时显示"Step Run"按钮（闪电图标），区别于"运行选中"。

---

#### P2-4 节点 Bypass/Mute（借鉴 ComfyUI）

**目标**：节点可跳过或静音，用于 A/B 对比和调试。

**实现**：
```javascript
// 节点 data 新增 mode 字段
node.data.mode = 0;  // 0=active, 1=mute, 2=bypass

// 渲染时视觉区分
if (node.data.mode === 1) el.classList.add('muted');    // 灰色半透明
if (node.data.mode === 2) el.classList.add('bypassed'); // 虚线边框

// 执行时
if (node.data.mode === 1) return;  // 跳过
if (node.data.mode === 2) {        // 透传
    // 找到上游 image_url，直接作为本节点输出
    const upstream_url = findUpstreamImage(node.id);
    registry.update(f"{canvas_id}:{node_id}", status="success", image_url=upstream_url);
    return;
}
```

**快捷键**：`Ctrl+B` 切换 Bypass，`Ctrl+M` 切换 Mute。

---

### P3：交互优化

#### P3-1 双击搜索添加节点（借鉴 ComfyUI）

**现状**：双击空白打开侧边栏选择节点类型。

**优化**：双击空白弹出搜索框，输入关键词模糊匹配节点类型，回车添加。

---

#### P3-2 复制粘贴双语义（借鉴 ComfyUI）

**现状**：`Ctrl+C/V` 复制粘贴选中子图。

**优化**：
- `Ctrl+C/V`：复制选中节点，不保留与未选中节点的连线
- `Ctrl+Shift+V`：复制选中节点，保留所有连线（包括与未选中节点的）

---

#### P3-3 连线渲染优化

**现状**：`renderConnections` 每次 `svg.innerHTML=''` 全量重建，拖拽时高频触发。

**优化**：
```javascript
// 增量更新：只更新受影响连线的 path d 属性
function updateConnectionPath(connId, d) {
    const path = document.getElementById(`conn-${connId}`);
    if (path) path.setAttribute('d', d);
    else { /* 新建 */ }
}

// 拖拽时节流
let renderRaf = null;
function scheduleRenderConnections() {
    if (renderRaf) return;
    renderRaf = requestAnimationFrame(() => {
        renderConnections();
        renderRaf = null;
    });
}
```

---

#### P3-4 Reroute 节点（借鉴 ComfyUI）

**目标**：纯走线整理节点，无逻辑，用于避免连线交叉。

**实现**：双击连线添加 Reroute 点，拖拽该点改变连线走向。

---

#### P3-5 分组与注释（借鉴 ComfyUI/n8n）

**目标**：`Ctrl+G` 框选节点创建分组，分组带标题/颜色/bounding box。

**数据结构**：
```javascript
canvasData.groups = [
    { id: "g1", title: "人像处理", color: "#3B82F6",
      nodes: ["node_a", "node_b"], bbox: {x, y, w, h} }
];
```

---

### P4：高级特性

#### P4-1 子工作流/模板组件化（借鉴 ComfyUI Blueprint）

**目标**：一组节点打包成可复用组件，在其他画布中作为单节点使用。

**场景**：把"AI 生图 → 抠图 → 遮罩编辑"打包成"人像处理"组件，拖入画布即用。

---

#### P4-2 批量 item 数组（借鉴 n8n）

**目标**：节点输出支持 item 数组，循环节点天然批处理。

**场景**：一组 prompt 参数生成多张海报变体，循环节点对每个 item 独立执行生图。

---

#### P4-3 子图 Blueprint（借鉴 ComfyUI）

**目标**：工作流可嵌套，子工作流作为独立节点。

---

#### P4-4 表达式编辑器（借鉴 n8n）

**目标**：参数字段可切换"固定值/表达式"，表达式引用上游变量。

**场景**：`{{upstream.width}}x{{upstream.height}}` 自动适配尺寸。

---

## 五、实施路线图

### 阶段一：架构基础（1-2 周）

| 任务 | 优先级 | 预估工时 | 风险 |
|---|---|---|---|
| P0-1 前端模块化拆分 | P0 | 3 天 | 低（功能不变，纯重构） |
| P0-2 后端模块化拆分 | P0 | 2 天 | 低 |
| P0-3 端口模型重构 | P0 | 4 天 | 中（数据结构变更，需迁移旧数据） |

**验收标准**：功能完全不变，旧画布数据可自动迁移，代码可读性显著提升。

---

### 阶段二：核心能力（2-3 周）

| 任务 | 优先级 | 预估工时 | 风险 |
|---|---|---|---|
| P1-1 VariablePool | P1 | 3 天 | 中 |
| P1-2 节点输出缓存 | P1 | 3 天 | 中（缓存失效策略需调优） |
| P1-3 错误处理三策略 | P1 | 2 天 | 低 |
| P1-4 WebSocket 实时通信 | P1 | 3 天 | 中（需处理断线重连） |

**验收标准**：AI 生图节点命中缓存不重算，节点失败可降级，实时状态推送延迟 < 100ms。

---

### 阶段三：调试与体验（2 周）

| 任务 | 优先级 | 预估工时 | 风险 |
|---|---|---|---|
| P2-1 Last Run Tracking | P2 | 2 天 | 低 |
| P2-2 Variable Inspect 面板 | P2 | 3 天 | 低 |
| P2-3 单节点 Step-Run | P2 | 1 天 | 低 |
| P2-4 Bypass/Mute | P2 | 1 天 | 低 |
| P3-1 双击搜索添加 | P3 | 0.5 天 | 低 |
| P3-2 复制粘贴双语义 | P3 | 0.5 天 | 低 |
| P3-3 连线渲染优化 | P3 | 1 天 | 低 |
| P3-4 Reroute 节点 | P3 | 1 天 | 低 |
| P3-5 分组与注释 | P3 | 1 天 | 低 |

**验收标准**：可单步调试节点，查看上次运行数据，A/B 对比不同参数效果。

---

### 阶段四：高级特性（按需）

| 任务 | 优先级 | 预估工时 | 风险 |
|---|---|---|---|
| P4-1 子工作流/模板组件化 | P4 | 5 天 | 高 |
| P4-2 批量 item 数组 | P4 | 4 天 | 高 |
| P4-3 子图 Blueprint | P4 | 5 天 | 高 |
| P4-4 表达式编辑器 | P4 | 3 天 | 中 |

---

## 六、即时可做的小优化（无需重构）

以下优化不依赖架构重构，可立即实施：

### 6.1 SQLite 连接池

```python
# 当前：每次 _persist 新建连接
def _persist(self, key, rec):
    conn = sqlite3.connect(self._db_path)  # 每次新建
    ...

# 优化：使用连接池或持久连接
class TaskRegistry:
    def __init__(self, db_path):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")  # 写并发优化
        self._lock = asyncio.Lock()
```

---

### 6.2 httpx 连接复用

```python
# 当前：每次请求新建 AsyncClient
async with httpx.AsyncClient(timeout=...) as client:
    resp = await client.post(...)

# 优化：全局复用 AsyncClient
class GptImageClient:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=...)
        self._sem = asyncio.Semaphore(3)

    async def generate(self, ...):
        async with self._sem:
            return await self._client.post(...)
```

---

### 6.3 getChainNodeIds 环检测

```python
# 当前：BFS 无环检测，画布有环时死循环
def getChainNodeIds(nodeId):
    const chain = new Set([nodeId]);
    const queue = [nodeId];
    while (queue.length) {
        const nid = queue.shift();
        for (const c of canvasData.connections) {
            if (c.to === nid && !chain.has(c.from)) { chain.add(c.from); queue.push(c.from); }
            // ...
        }
    }
}

# 优化：限制遍历深度
function getChainNodeIds(nodeId, maxDepth = 100) {
    const chain = new Set([nodeId]);
    const queue = [{id: nodeId, depth: 0}];
    while (queue.length) {
        const {id: nid, depth} = queue.shift();
        if (depth >= maxDepth) continue;  // 防环
        // ...
    }
}
```

---

### 6.4 前端轮询聚合

```javascript
// 当前：每节点独立 setInterval
pollTimers[nodeId] = setInterval(async () => {
    const r = await _apiFetch(`/api/canvas/${currentCanvasId}/nodes/${nodeId}`);
    // ...
}, 800);

// 优化：单定时器批量拉取
let pollTimer = null;
function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
        if (!currentCanvasId) return;
        const r = await _apiFetch(`/api/canvas/${currentCanvasId}/nodes`);
        const nodes = await r.json();
        nodes.forEach(d => updateNodeUI(d.node_id, d));
    }, 800);
}
```

---

### 6.5 日志聚合与结构化

```python
# 当前：logging.basicConfig，无结构化
logger.error("node %s:%s failed: %s", canvas_id, node_id, e)

# 优化：结构化日志
import structlog
logger = structlog.get_logger()
logger.info("node_executed",
    canvas_id=canvas_id, node_id=node_id, node_type=node_type,
    status="success", elapsed_ms=elapsed, token_cost=tokens)
```

---

## 七、总结

### 核心结论

1. **Dify 的画布设计与本项目契合度最高**（语义化端口 + VariablePool + Last Run 调试 + 三策略错误处理），建议作为主要参考
2. **ComfyUI 的类型系统 + 缓存机制 + WebSocket 事件**是技术架构的核心借鉴
3. **当前项目最大瓶颈是端口模型和变量系统**，应优先重构（P0-3）
4. **前端单文件巨石**是维护性的最大债务，应优先拆分（P0-1）

### 优先级排序

```
P0（架构基础）→ P1（核心能力）→ P2（调试体验）→ P3（交互优化）→ P4（高级特性）
    ↓                ↓                ↓                ↓                ↓
 1-2周            2-3周            2周             1周             按需
```

### 风险控制

- **P0-3 端口模型重构**风险最高（数据结构变更），需做旧数据自动迁移 + 灰度发布
- **P1-2 缓存机制**需仔细设计失效策略，避免缓存脏数据
- **P1-4 WebSocket**需处理断线重连和消息丢失
- 所有重构保持功能不变，增量迁移，旧代码逐步删除

---

## 参考资料

### ComfyUI
- [ComfyUI Core Architecture (DeepWiki)](https://deepwiki.com/Comfy-Org/ComfyUI/2-core-architecture)
- [Workflow JSON Spec](https://docs.comfy.org/specs/workflow_json)
- [Links - Color-coding](https://docs.comfy.org/development/core-concepts/links)
- [Keyboard Shortcuts](https://docs.comfy.org/interface/shortcuts)
- [Subgraph 功能](https://docs.comfy.org/zh/interface/features/subgraph)

### Dify
- [Dify 1.5.0 实时工作流调试](https://dify.ai/blog/dify-1-5-0-real-time-workflow-debugging-that-actually-works)
- [Workflow System Fundamentals](https://deepwiki.com/langgenius/dify-docs/4-workflow-system-fundamentals)
- [Error Handling 文档](https://legacy-docs.dify.ai/guides/workflow/error-handling)

### Coze
- [Coze 工作流使用攻略 2026](https://blog.csdn.net/He_CSDN2025/article/details/161117315)
- [Coze 大模型节点官方文档](https://www.coze.cn/open/docs/guides/llm_node)

### n8n
- [n8n Expressions 文档](https://docs.n8n.io/data/expressions/)
- [n8n Error Handling Production Guide](https://www.n8nflow.net/blog/n8n-error-handling-reliability-guide)
