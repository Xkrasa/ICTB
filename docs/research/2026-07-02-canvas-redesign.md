# 画布深度重构方案：大图节点 + 浮层参数面板

**日期**：2026-07-02
**范围**：`static/app.js` + `static/styles.css` + `index.html`
**目标**：将现有"内嵌参数栏卡片"节点重构为"大图预览为主 + 参数以浮层形式呈现"的极客风格画布，视觉逼近旧版 RunningHub / ai-flow 平台

---

## 一、当前实现的核心痛点

对照当前 `buildNodeBody`（[app.js#L314-L508](file:///e:/Poster_tuanbo/static/app.js#L314-L508)）梳理：

| 痛点 | 现状 | 影响 |
|---|---|---|
| **参数栏挤占预览** | prompt 输入框 + toolbar + 3~4 个参考图槽位全部塞进节点内 | 图片预览被压缩到 60~80px 高，看不清效果 |
| **节点尺寸不一** | image_input ≈ 210×170，gpt_image ≈ 220×280，seedance ≈ 240×380 | 画布视觉杂乱、连线走向不规则 |
| **状态徽章占位** | 顶部 header 34px 高，图标+标题+徽章 | 节点内容纵向空间被压缩 |
| **参考图槽位太小** | 3 个 flex:1 平分，单个≈50×50 | 上游产物看不出细节 |
| **端口太细小** | 12×12 圆点，仅节点色描边 | 拖拽连线难瞄准，端口意义靠猜 |
| **连线太朴素** | 单色曲线 + 3px 描边 | 无法直观看出数据流方向和状态 |
| **无法批量对齐** | 节点尺寸不一致，无法对齐格栅 | 大画布排版困难 |

## 二、旧版画布的设计精髓（已实证）

从 `工作流画布.html` 解析出的真实结构：

```html
<div class="vue-flow__node vue-flow__node-custom">
  <div class="node-container pos-relative w-full h-full">
    <!-- 标题浮在节点外：-translate-y-full 让 input 完全在节点上方 -->
    <div class="absolute top-0 -translate-y-full text-[#666] nodrag">
      <span class="ant-input-affix-wrapper input-wrapper">
        <span class="ant-input-prefix"><svg .../></span>
        <input readonly value="节点ID/名称" />
      </span>
    </div>

    <!-- 内容铺满整个节点：absolute inset-0 -->
    <div class="image-node absolute inset-0">
      <div class="absolute inset-0 w-full h-full flex-center">
        <img src="..." />  <!-- 或 <video controls> -->
      </div>
    </div>

    <!-- 端口：大号圆 + plus-circle 图标 -->
    <div class="vue-flow__handle vue-flow__handle-right ...">
      <div class="node-handle node-handle-right">
        <span class="anticon anticon-plus-circle node-handle-plus">
          <svg .../><!-- plus 图标 -->
        </span>
      </div>
    </div>
  </div>
</div>
```

**核心设计哲学**：**"内容即节点"**

- **节点=预览容器**：图片/视频撑满整个节点
- **元信息浮出**：ID/名称浮在节点上方，不占内容空间
- **端口是主角**：大号圆形 + `+` 图标，视觉重量堪比按钮
- **参数在别处**：所有编辑操作在"节点外"完成（浮层面板 / 右侧栏 / 双击进入）

---

## 三、方案总览

### 3.1 节点视觉重构（3 层结构）

```
┌────────────────────────────────┐
│  ⓘ 图1 · 主体图    [完成]      │  ← 标题浮层（悬浮在节点上方，不占内容空间）
├────────────────────────────────┤
│                                │
│         [ 240 × 240 ]          │  ← 预览层（主体，占满节点）
│           大图预览              │
│                                │
├────────────────────────────────┤
│  1024×1024 · gpt-image-2       │  ← 元信息浮层（悬浮在节点下方）
└────────────────────────────────┘
       ↕ 展开时 (点击/双击)
┌────────────────────────────────┐
│  参数面板浮层（Figma 风格）      │
│  - Prompt                      │
│  - Model / Ratio / Size        │
│  - Reference Slots             │
└────────────────────────────────┘
```

### 3.2 尺寸规范

| 节点类型 | 尺寸 | 说明 |
|---|---|---|
| image_input | 240×240 | 正方形，纯图预览 |
| gpt_image | 240×240 | 正方形，预览为主，参数进浮层 |
| remove_bg | 240×240 | 正方形，纯图预览 |
| seedance_video | 240×280 | 竖屏 (视频通常竖屏)，参数进浮层 |
| mask_edit | 240×240 | 正方形，遮罩叠加预览 |

**取消现有的"横向紧凑"布局**，统一到 240 宽度，视觉整齐。

### 3.3 端口重构

```
现状：       重构后：
                     ┌─────┐
   ○  →       │  ⊕  │    (24×24, plus-circle 图标, 类型化配色)
                     └─────┘
```

- **尺寸**：从 12×12 提到 22×22
- **图标**：中央嵌 `plus-circle` SVG (Ant Design Icons)
- **配色**：
  - 输入端口：绿色 → 表示"接收数据"
  - 输出端口：蓝色 → 表示"输出数据"
  - Hover 时：`scale(1.25)` + 发光
  - 连接中：脉冲动画
- **可点击热区**：外围 32×32 无形 padding，命中率大幅提升

### 3.4 连线重构

- **贝塞尔曲率**：控制点 `dx = (toX - fromX) * 0.5`，更符合工作流平台习惯
- **描边动画**：`stroke-dasharray` + `animation` 流水灯，运行中的连线数据流可视化
- **状态配色**：
  - 待机：`--text-4` (灰)
  - 运行中：`--primary` (紫) + 流水动画
  - 已完成：`--success` (绿)
  - 失败：`--danger` (红)
- **hover/selected**：加粗 + 发光光晕

### 3.5 状态徽章新位置

```
不在标题栏里，改为浮层：
┌──[完成]─────────────┐
│                     │
│      节点预览        │
│                     │
└─────────────────────┘
```

- **位置**：节点右上角，`translate(50%, -50%)` 浮出
- **样式**：胶囊按钮，圆角 12px，图标 + 文字
- **动画**：running 状态呼吸动画（已实现）+ 转圈图标

---

## 四、浮层参数面板（Figma 风格）

### 4.1 触发方式

| 交互 | 行为 |
|---|---|
| **单击节点** | 选中节点，参数面板浮层从节点右侧滑出 |
| **双击节点** | 弹出参数面板并聚焦第一个可编辑字段（快速编辑） |
| **右键节点** | 上下文菜单：编辑参数 / 复制 / 删除 |
| **点击画布空白** | 关闭浮层 |
| **ESC** | 关闭浮层 |

### 4.2 浮层布局

```
┌────────────────────────────────────┐
│ ⚙️ AI 生图 · gpt-image-2  ✕        │  ← 头部（模型标签 + 关闭按钮）
├────────────────────────────────────┤
│ ▼ 基础参数                          │  ← 可折叠分组
│   Prompt                           │
│   [                        ]       │
│   [ 大文本框，8行             ]       │
│   [                        ]       │
│                                    │
│   Model      [ gpt-image-2  ▼ ]    │
│   Ratio      [ 1:1          ▼ ]    │
│   Size       [ 1024x1024    ▼ ]    │
├────────────────────────────────────┤
│ ▼ 参考图                            │
│   [ 图1 · 上游 ] [ 图2 · 发型 ]     │
│   [ 图3 · 服装 ]                    │
├────────────────────────────────────┤
│ ▶ 高级选项                          │  ← 默认折叠
└────────────────────────────────────┘
```

### 4.3 定位策略

- **默认停靠**：节点右侧 12px 处，与节点上边缘对齐
- **超出视口**：自动翻转到节点左侧
- **可拖拽移动**：头部可拖，位置持久化到 `localStorage`
- **可最小化**：折叠到只剩标题栏
- **z-index**：高于节点、低于模态框（`z: 1500`）

### 4.4 与画布的关系

- **面板不占画布位置**：浮在画布之上，跟随节点位置
- **画布平移/缩放时**：面板位置跟随节点，但**尺寸和字号不受缩放影响**（`transform` 只对节点，不对面板）
- **多选节点**：面板隐藏（避免歧义），改用底部批量操作栏

---

## 五、实施拆解（分 4 个阶段）

### 阶段 1：节点视觉重构（核心，最大改动）

**改动文件**：`app.js` + `styles.css`

- 重写 `buildNodeHTML`：三层结构（标题浮层 / 预览层 / 元信息浮层）
- 重写 `buildNodeBody`：**只保留预览**，删除所有 select/textarea/refSlot
- 新增 `.node-title-float`（顶部浮层）
- 新增 `.node-meta-float`（底部浮层）
- 新增 `.node-status-float`（右上角状态徽章）
- 节点统一尺寸 240×240（视频节点 240×280）

**函数增删**：
- 删除：内嵌 prompt / toolbar / refSlot 相关模板
- 保留：`updateNodeUI` / `refreshNodePreview` / 端口事件

### 阶段 2：端口重构

- 端口 DOM 加 SVG `plus-circle` 图标
- 尺寸 12→22，热区 32
- 类型化配色（输入绿、输出蓝）
- Hover 动画（`scale + glow`）
- 拖拽连线时脉冲动画

### 阶段 3：连线重构

- SVG 描边动画（`stroke-dashoffset`）
- 状态配色映射
- Hover 加粗 + 发光
- 曲率优化

### 阶段 4：浮层参数面板（新组件）

- 新建 DOM 容器 `#node-params-panel`
- 组件化：`renderParamsPanel(nodeId)`
- 按节点类型分区渲染参数
- 定位算法（右侧优先，越界翻转）
- 折叠 / 拖拽 / 关闭
- localStorage 持久化位置

---

## 六、参数面板的字段映射

按现有 `getDefaultData` 结构梳理每种节点的参数：

### image_input
- **参数**：上传按钮 + 清除按钮
- **面板简化**：这类节点参数极少，可考虑**不显示浮层**，直接节点内保留上传按钮

### gpt_image
- **基础参数**：`prompt` / `model`
- **模型参数**：
  - gpt-image-2: `size`
  - rh_gpt_image_i2i / nano_banana_2: `aspect_ratio` / `resolution`
- **参考图**：`image_url` (只读，图1) / `hair_url` / `clothing_url` / `image2_url` / `image3_url` / `image4_url`
- **动作**：润色按钮 / 成本提示

### remove_bg
- **参数**：无，纯管道节点

### mask_edit
- **参数**：无编辑参数（遮罩通过双击进入编辑器绘制）
- **面板显示**：只读的上游来源提示 + "双击编辑遮罩" 按钮

### seedance_video
- **基础参数**：`prompt` / `channel`
- **模型参数**：`aspect_ratio` / `duration` / `resolution` (仅首尾帧模式)
- **参考图**：`image_url` (首帧) / `image2_url` (尾帧)
- **动作**：成本提示

---

## 七、边缘情况和风险

### 7.1 现有交互兼容
- **拖拽连线**：不受影响（端口 DOM 结构不变，只改视觉）
- **双击编辑遮罩**：保留
- **Ctrl+C / Ctrl+V**：保留
- **框选 / 多选**：保留（浮层参数在多选时隐藏）
- **撤销 / 重做**：不受影响

### 7.2 数据兼容
- **localStorage 现有画布**：节点 data 结构不变，兼容现有已保存画布
- **旧节点导入**：`migrateNodeData` 保留不变

### 7.3 性能
- **参数面板懒加载**：只在选中节点时渲染，切换节点时销毁重建
- **节点尺寸增大**：小地图缩放比例调整
- **连线动画**：CSS animation 而非 JS，无性能开销

### 7.4 已知风险
| 风险 | 缓解 |
|---|---|
| 节点变大后画布可容纳数量减少 | 调整默认 `viewScale=0.9` + `viewport` 内边距 |
| 参数面板遮挡下游节点 | 提供快捷键 `ESC` 关闭 + 半透明背景 |
| 手机端不适配 | 本项目仅桌面，忽略 |
| 旧样式变量残留 | 阶段 1 之后集中清理未使用样式 |

---

## 八、验收标准

### 8.1 视觉验收
- [ ] 所有节点尺寸统一（240×240 或 240×280）
- [ ] 图片预览至少 220×220 有效面积（不被参数遮挡）
- [ ] 端口清晰可见 + 拖拽命中率高
- [ ] 连线状态色区分明显（running / success / failed）
- [ ] 状态徽章浮出，不遮挡预览

### 8.2 交互验收
- [ ] 单击节点 → 参数面板浮层从右侧滑出
- [ ] 双击节点 → 面板打开且第一个字段获焦
- [ ] ESC / 点击画布空白 → 关闭面板
- [ ] 拖拽面板可移动，位置持久化
- [ ] 折叠分组正常展开收起
- [ ] 修改参数实时同步到 `node.data` 并触发 `autoSave`

### 8.3 兼容性验收
- [ ] 现有 canvas.json 加载正常显示
- [ ] `runCanvas` / `runSelected` 逻辑不受影响
- [ ] 拖拽连线正常
- [ ] 撤销/重做正常
- [ ] 多选 / 框选 / 剪切板正常

---

## 九、代码骨架预览

### 9.1 新的 buildNodeHTML

```javascript
function buildNodeHTML(node, cfg) {
  const rt = nodeRuntime[node.id] || {};
  const status = rt.status || 'idle';
  const inPort = node.type === 'image_input' ? '' : `
    <div class="port port-in" data-port="in">
      <svg class="port-icon"><use href="#icon-plus-circle"/></svg>
    </div>`;
  const outPort = `
    <div class="port port-out" data-port="out">
      <svg class="port-icon"><use href="#icon-plus-circle"/></svg>
    </div>`;
  const iconSvg = cfg.icon ? `<svg class="node-icon-svg"><use href="#icon-${cfg.icon}"/></svg>` : '';

  return `${inPort}${outPort}
    <div class="node-title-float">
      <span class="node-icon">${iconSvg}</span>
      <span class="node-title">${cfg.title}</span>
    </div>
    <div class="node-status-float">
      <span class="node-badge ${status}" id="badge-${node.id}">${STATUS_LABELS[status]}</span>
      <button class="node-delete" onclick="removeNode('${node.id}')">✕</button>
    </div>
    <div class="node-preview-layer">${buildNodePreview(node)}</div>
    <div class="node-meta-float">${buildNodeMeta(node)}</div>
    <div class="node-progress-bar"><div class="fill" id="prog-${node.id}"></div></div>`;
}

function buildNodePreview(node) {
  const d = node.data;
  // 视频节点特殊处理
  if (node.type === 'seedance_video' && d.video_url) {
    return `<video src="${d.video_url}" muted loop autoplay
             onclick="openLightbox('${d.video_url}',true)"></video>`;
  }
  // mask_edit 特殊处理：叠加遮罩
  if (node.type === 'mask_edit') {
    return buildMaskPreview(node);
  }
  // 通用图片预览
  if (d.image_url) {
    return `<img src="${d.image_url}" onclick="openLightbox('${d.image_url}')"/>`;
  }
  return `<div class="preview-empty">${getEmptyIcon(node.type)}</div>`;
}

function buildNodeMeta(node) {
  const d = node.data;
  const parts = [];
  if (d._width && d._height) parts.push(`${d._width}×${d._height}`);
  if (d.model) parts.push(d.model);
  if (d.channel) parts.push(d.channel);
  if (d.aspect_ratio) parts.push(d.aspect_ratio);
  return parts.join(' · ') || '&nbsp;';
}
```

### 9.2 参数面板骨架

```javascript
let paramsPanel = null;
let paramsPanelNodeId = null;

function openParamsPanel(nodeId, focusFirst=false) {
  const node = canvasData.nodes.find(n => n.id === nodeId);
  if (!node) return;
  paramsPanelNodeId = nodeId;
  if (!paramsPanel) {
    paramsPanel = document.createElement('div');
    paramsPanel.id = 'node-params-panel';
    document.body.appendChild(paramsPanel);
    bindPanelDrag();
  }
  paramsPanel.innerHTML = renderParamsPanel(node);
  paramsPanel.classList.add('open');
  positionPanel(node);
  if (focusFirst) {
    const first = paramsPanel.querySelector('textarea, input, select');
    if (first) first.focus();
  }
}

function closeParamsPanel() {
  if (paramsPanel) paramsPanel.classList.remove('open');
  paramsPanelNodeId = null;
}

function renderParamsPanel(node) {
  const cfg = NODE_CFG[node.type];
  const groups = getParamsGroups(node);  // 按类型返回分组的参数字段
  return `
    <div class="pp-header">
      <span class="pp-title">${cfg.title}</span>
      <button class="pp-close" onclick="closeParamsPanel()">✕</button>
    </div>
    <div class="pp-body">
      ${groups.map(g => `
        <div class="pp-group ${g.collapsed ? 'collapsed' : ''}">
          <div class="pp-group-title" onclick="togglePanelGroup(this)">
            <span class="chev">▶</span>${g.title}
          </div>
          <div class="pp-group-body">${g.render(node)}</div>
        </div>
      `).join('')}
    </div>
  `;
}
```

---

## 十、下一步

**用户已确认的决策**（2026-07-02）：

1. ✅ 节点尺寸 240×240（视频节点 240×280）
2. ✅ 参数面板从**画布底部**滑出（全宽底栏，类似 Figma / VSCode 属性面板）
3. ✅ **完全清空节点内 UI**（只保留预览 + 标题浮层 + 状态浮层 + 进度条）
4. ✅ 进度条在节点底部
5. ✅ 视频节点保持"点击才播放"（不 autoplay）
6. ✅ 允许引入 Vue/React，只要效果好（本次先用纯 JS 完成，避免大规模重写）

---

## 附：不做的事（避免过度设计）

- ❌ 不引入 Vue / React（保留纯 JS）
- ❌ 不引入 Vue Flow / React Flow / litegraph 库
- ❌ 不做手机端适配
- ❌ 不做多主题切换
- ❌ 不做节点子工作流（另开新特性）
- ❌ 不改后端 API
- ❌ 不做参数模板 / 参数版本历史（另开新特性）
