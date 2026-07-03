# 画布架构升级方案：一键流程 · 多入参语义 · 项目化 · 批准模式

**日期**：2026-07-02
**目标**：解决当前画布工作流在生产使用中遇到的 4 个核心问题

---

## 一、问题 1：全流程一键走完（关键瓶颈：遮罩编辑）

### 现状

当前 `runCanvas` / `runSelected` 已经是 DAG 级联执行，纯图片链路可以一键跑完：

```
图片输入 → AI 生图 → 抠图 → AI 生图 → ...
```

但视频链路被**遮罩编辑**卡住：

```
图片输入 → AI 生图 → 遮罩编辑（必须人工画） → 视频生成
```

`mask_edit` 节点依赖人工在 canvas 上涂抹，导致"一键跑完全链路"必然中断。

### 解决思路

你的核心诉求是：**视频生成不能出现真人，必须用遮罩遮住人脸，但固定模板很难精确覆盖人脸**。因此遮罩自动化必须围绕"人脸定位"来做，而不是姿态模板。

#### 方案 A：人脸检测自动遮罩（已实施）

后端基于输入图自动检测人脸，生成只覆盖人脸区域的二值遮罩：

- **检测方式**：使用 OpenCV Haar 级联分类器（无需额外模型文件）
- **遮罩生成**：
  - 以人脸 bbox 为中心绘制椭圆遮罩（覆盖全脸）
  - 通过 `expand` 参数做形态学膨胀，扩展 10%~60%，确保发际线、下巴也被遮住
  - 边缘羽化使过渡更自然
- **输出**：`mask_url` 为黑底白脸（白色为保留区域）的二值 PNG

**验证结果**（合成人脸 + OpenCV Haar）：

| 场景 | expand=0.25 覆盖率 |
|---|---|
| 正面大脸 | 65.3% |
| 正面小脸 | 22.0% |
| 偏左脸 | 41.9% |
| 偏右脸 | 44.5% |
| 宽屏图小脸 | 9.6% |
| 竖屏图大脸 | 29.2% |

6 种场景全部检测成功；expand 参数生效（0.0→27.5%，0.25→42.6%，0.6→69.8%）。

**优点**：一键跑通；针对"规避真人"场景最精准。
**缺点**：Haar 对侧脸/遮挡/多人脸场景较敏感；检测失败时 fallback 到全图遮罩。

#### 方案 B：自动全图遮罩（兜底）

如果人脸检测失败，或用户想保留整个人物：

- 上游是透明 PNG → 全白遮罩（全保留）
- 上游是不透明图 → 全图遮罩或主体分割遮罩

作为 **A 失败后的 fallback**。

#### 方案 C：批量 / 异步人工队列

如果自动人脸遮罩效果不够理想：

- 一键运行时，遇到 `mask_edit` 节点自动**暂停整个画布**
- 弹出待办列表（"请完成以下 N 个遮罩编辑"）
- 用户基于自动预生成的人脸遮罩进行微调，确认后继续
- 所有 `mask_edit` 都完成后，自动恢复执行下游

**优点**：保留人工质量；自动预生成可以大幅减少涂抹工作量。
**缺点**：严格来说不是"一键"，是一键启动 + 人工补完。

### 推荐组合

| 场景 | 方案 |
|---|---|---|
| 你的核心场景 | **A 为主**：自动检测人脸并生成遮罩，直接跑通视频链路 |
| A 检测失败 | B 兜底：全图遮罩或主体遮罩 |
| 需要精修 | C：自动人脸遮罩预填充，用户微调后继续 |

### 涉及改动

- 后端：新增 `mask_service.py`
  - `detect_face_mask(image_bytes, expand=0.2, method='mediapipe') → mask_bytes`
  - `generate_full_mask(image_bytes) → mask_bytes`
- 后端：`orchestrator.py` 的 `exec_mask_edit` 增加 `mode` 参数
  - `auto_face`：自动人脸遮罩
  - `auto_full`：全图遮罩
  - `manual`：人工绘制（保留现有编辑器）
- 前端：`mask_edit` 参数面板增加模式选择
  - 默认 `auto_face`
  - 检测到多人脸时提示用户选择或切 manual
- 依赖：`requirements.txt` 增加 `mediapipe` 或 `dlib`（建议 mediapipe，纯 pip 安装更稳定）

---

## 二、问题 2：生成节点多入参的分配与对齐

### 现状

一个视频节点接入两个 AI 生图节点时：

- 当前没有语义，只能按连线数组顺序取第一个
- 用户无法指定"这个是首帧""这个是尾帧"
- 换个连法顺序就错

### 根本问题

当前连线模型只有 `from` 和 `to`：

```json
{ "id": "c1", "from": "gpt-A", "to": "seedance" }
```

没有表达"连到视频节点的哪个输入口"的信息。

### 解决思路：端口语义化（Ports with fields）

每个节点暴露带名字的输入/输出端口：

```json
{
  "type": "seedance_video",
  "inputs": [
    { "name": "first_frame",  "type": "IMAGE", "label": "首帧" },
    { "name": "last_frame",   "type": "IMAGE", "label": "尾帧（可选）" },
    { "name": "prompt",       "type": "TEXT",  "label": "视频描述" }
  ],
  "outputs": [
    { "name": "video", "type": "VIDEO", "label": "生成视频" }
  ]
}
```

连线也带 `fromField` / `toField`：

```json
{ "id": "c1", "from": "gpt-A", "fromField": "image",
  "to": "seedance", "toField": "first_frame" }
```

前端渲染端口时，每个输入口有明确标签和颜色：

```
        ┌───────────┐
  首帧 ●│ 视频生成   │● 视频
  尾帧 ●│           │
        └───────────┘
```

### 兼容现有数据

- 旧连线只有 `from/to`，自动升级：
  - 目标节点第一个必需输入口 = `toField`
  - 源节点第一个输出口 = `fromField`
- 新保存的画布都带字段名

### 涉及改动

- 数据结构：`canvasData.connections` 增加 `fromField` / `toField`
- 后端：`orchestrator.py` 的 `_inject_upstream_to_downstreams` 按字段名注入
- 前端：`renderNode` 按节点类型渲染多个输入口/输出口
- 前端：拖拽连线时目标端口高亮，连完记录字段名

### 与问题 1 的关系

`mask_edit` 也要有明确输入端口：

```json
{
  "type": "mask_edit",
  "inputs": [
    { "name": "image", "type": "IMAGE", "label": "待编辑图" }
  ],
  "outputs": [
    { "name": "mask", "type": "MASK", "label": "遮罩" }
  ]
}
```

这样视频节点才能区分：

```
AI 生图 A ──first_frame──→ 视频生成
AI 生图 B ──last_frame──→ 视频生成
```

---

## 三、问题 3：画布项目化

### 现状

- 只有一个当前画布
- 左侧历史/模板列表较简陋
- 不能"新建项目"、"复制项目"、"删除项目"

### 目标

像 ComfyUI / Dify / Coze 一样：

```
工作空间
  ├── 项目 A / 海报生成
  │     ├── v1（画布快照）
  │     └── v2
  ├── 项目 B / 短视频
  └── 模板库
        ├── 9:16 人物海报模板
        └── 16:9 横版模板
```

### 数据模型

新增 SQLite 表（`projects`）：

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at REAL,
    updated_at REAL,
    is_template INTEGER DEFAULT 0,  -- 1 = 模板，0 = 普通项目
    thumbnail_url TEXT
);

CREATE TABLE project_canvases (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    version INTEGER,
    name TEXT,
    data TEXT,  -- JSON: nodes + connections
    created_at REAL,
    updated_at REAL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
```

### 功能列表

| 功能 | 说明 |
|---|---|
| 新建项目 | 从空白画布或模板创建 |
| 复制项目 | 复制当前画布为新项目 |
| 删除项目 | 软删除或硬删除 |
| 保存版本 | 同一项目保留多个版本 |
| 设为模板 | 项目标记为模板，供新建时选择 |
| 项目列表 | 左侧/顶部抽屉展示 |

### 涉及改动

- 后端：`main.py` 增加 `/api/projects`、`/api/projects/{id}`、`/api/projects/{id}/versions` 接口
- 后端：`storage.py` 或新增 `projects.py` 管理 SQLite
- 前端：左侧新增"项目/模板"抽屉
- 前端：顶部工具栏"文件"菜单（新建/打开/保存/另存为/删除）

---

## 四、问题 4：批准模式

### 需求

用户希望有一个开关：

- 开启"批准模式"后，每个 AI 生成节点（AI 生图、视频生成等）产出后**暂停**
- 用户查看结果，决定：
  - ✅ 批准：继续执行下游
  - ❌ 拒绝：终止该分支 / 重新生成
- 关闭批准模式：正常一键跑完

### 状态机

节点状态增加 `awaiting_approval`：

```
idle → pending → running → awaiting_approval → approved → success → 触发下游
                                              → rejected → failed → 阻断下游
```

### 前端交互

每个节点成功后如果开启批准模式：

- 状态徽章显示"待批准"
- 预览层出现两个按钮：「✅ 通过」「❌ 重试/拒绝」
- 点击通过后，下游继续运行
- 点击拒绝后，该节点失败，下游 blocked

### 批准粒度

按你的反馈，**只需要全局开关**：

- 工具栏一个「批准模式」开关
- 开启后，所有 AI 生成节点（`gpt_image`、`seedance_video`）产出后自动暂停，状态变为 `awaiting_approval`
- 用户点击「通过」后继续执行下游；点击「重试/拒绝」则该节点失败，下游 blocked
- 关闭开关时，恢复当前一键跑完全链路的行为

### 涉及改动

- 后端：`orchestrator.py`
  - 节点成功后，如果画布启用了批准模式，状态改为 `awaiting_approval`，不继续级联
  - 新增 `/api/canvas/{canvas_id}/approve/{node_id}`：节点通过，继续级联
  - 新增 `/api/canvas/{canvas_id}/reject/{node_id}`：节点拒绝，标记 failed 并阻断下游
- 前端：工具栏增加「批准模式」开关（保存到画布数据或 localStorage）
- 前端：`updateNodeUI` 处理 `awaiting_approval` 状态，节点卡片渲染「通过 / 拒绝」按钮

---

## 五、4 个问题的优先级与依赖关系

```
问题 2（端口语义化）
        │
        ▼
问题 1（遮罩自动化） ←──── 依赖端口语义化
        │
        ▼
问题 4（批准模式）   ←──── 依赖稳定的节点状态机和端口模型
        │
        ▼
问题 3（画布项目化） ←──── 最后做，依赖画布数据结构稳定
```

**建议实施顺序**：2 → 1 → 4 → 3

---

## 六、短期折中方案（如果希望快速见效）

如果不打算一次性大改，可以先做：

1. **遮罩节点增加"全图通过"自动模式**（后端改动小，1 天可完成）
2. **视频节点输入按连线顺序固定语义**：第一条 = 首帧，第二条 = 尾帧（文档约定，不改端口模型）
3. **工具栏加一个"批准模式"复选框**，生成节点成功后暂停并弹确认（前端为主）
4. **项目化延后到下一版**

---

## 七、需要用户确认的关键决策

1. **遮罩自动化**：接受"全图自动遮罩 / 模板遮罩"方案吗？还是需要必须人工干预？
2. **端口语义化**：是否接受改造连线模型（`fromField/toField`）？这是问题 2/4 的基础。
3. **批准模式**：只需要全局开关，还是需要每个节点单独设置？
4. **项目化**：优先做"新建/复制/删除项目"，还是先做"版本历史"？
5. **实施节奏**：按依赖顺序 2→1→4→3 做，还是先快速折中方案跑起来？
