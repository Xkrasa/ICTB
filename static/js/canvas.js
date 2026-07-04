// ═══ 画布模式（canvas.js）═══
// 节点/连线/端口/遮罩/参数面板/运行/轮询/批准/对比/小地图/保存
    function uid() { return Math.random().toString(36).slice(2, 10); }

    // ═══════════════════════════════════════════════════════════════
    // 撤销 / 重做（快照式：仅记录结构性变更，不含文本编辑）
    // ═══════════════════════════════════════════════════════════════
    let undoStack = [], redoStack = [];
    const MAX_HISTORY = 60;
    function snapshotCanvas() {
      return JSON.parse(JSON.stringify({ nodes: canvasData.nodes, connections: canvasData.connections }));
    }
    function pushHistory() {
      undoStack.push(snapshotCanvas());
      if (undoStack.length > MAX_HISTORY) undoStack.shift();
      redoStack = [];
      updateUndoRedoButtons();
    }
    function restoreSnapshot(snap) {
      canvasData.nodes.forEach(n => stopPolling(n.id));
      Object.values(nodeElements).forEach(el => el.remove());
      Object.keys(nodeElements).forEach(k => delete nodeElements[k]);
      canvasData = JSON.parse(JSON.stringify(snap));
      selectedNode = null; selectedConn = null;
      canvasData.nodes.forEach(renderNode);
      renderConnections();
      updateStatusbar();
      updateRunSelectedBtn();
      autoSave();
    }
    function undo() {
      if (undoStack.length === 0) return;
      redoStack.push(snapshotCanvas());
      restoreSnapshot(undoStack.pop());
      updateUndoRedoButtons();
    }
    function redo() {
      if (redoStack.length === 0) return;
      undoStack.push(snapshotCanvas());
      restoreSnapshot(redoStack.pop());
      updateUndoRedoButtons();
    }
    function updateUndoRedoButtons() {
      const u = document.getElementById('btn-undo'), r = document.getElementById('btn-redo');
      if (u) u.disabled = undoStack.length === 0;
      if (r) r.disabled = redoStack.length === 0;
    }

    // ═══════════════════════════════════════════════════════════════
    // 视口变换
    // ═══════════════════════════════════════════════════════════════
    function applyTransform() {
      document.getElementById('workspace').style.transform = `translate(${viewX}px,${viewY}px) scale(${viewScale})`;
      document.getElementById('zoom-display').textContent = Math.round(viewScale * 100) + '%';
      scheduleMinimap();
    }
    function resetView() { viewX = 100; viewY = 70; viewScale = 1; applyTransform(); }
    function zoomBy(f) {
      const r = document.getElementById('viewport').getBoundingClientRect();
      const cx = r.width/2, cy = r.height/2;
      const wx = (cx-viewX)/viewScale, wy = (cy-viewY)/viewScale;
      viewScale = Math.max(0.2, Math.min(3, viewScale*f));
      viewX = cx - wx*viewScale; viewY = cy - wy*viewScale;
      applyTransform();
    }
    function screenToCanvas(sx, sy) { return { x: (sx-viewX)/viewScale, y: (sy-viewY)/viewScale }; }

    // ═══════════════════════════════════════════════════════════════
    // 节点管理
    // ═══════════════════════════════════════════════════════════════
    function addNode(type) {
      const r = document.getElementById('viewport').getBoundingClientRect();
      const c = screenToCanvas(r.width/2, r.height/2);
      addNodeAt(type, c.x, c.y);
    }
    function openSidePanel() {
      document.getElementById('side-panel').classList.add('open');
      document.getElementById('side-panel-overlay').classList.add('show');
    }
    function closeSidePanel() {
      document.getElementById('side-panel').classList.remove('open');
      document.getElementById('side-panel-overlay').classList.remove('show');
    }
    function addNodeFromPanel(type) {
      addNode(type);
      closeSidePanel();
    }
    function addNodeAt(type, x, y) {
      pushHistory();
      const node = { id: uid(), type, x: x-105, y: y-50, data: getDefaultData(type) };
      canvasData.nodes.push(node);
      renderNode(node);
      updateStatusbar();
      hideContextMenu();
      autoSave();
    }
    function getDefaultData(type) {
      switch (type) {
        case 'image_input': return { image_url: null };
        case 'gpt_image': return { prompt:'', hair_url:'', makeup:'', clothing_url:'', model:'gpt-image-2', size:'1024x1024', image1:'', image2:'', image2_url:'', image3_url:'', image4_url:'', mj_version:'Midjourney V7' };
        case 'remove_bg': return {};
        case 'mask_edit': return { mask_url: null, mask_mode: 'auto_face' };
        case 'seedance_video': return { prompt:'', duration:'8', aspect_ratio:'9:16', channel:'official', first_frame:'', last_frame:'', image_url:'', image2_url:'', resolution:'480p', video_url:'', generate_audio:false, real_person_mode:false };
        default: return {};
      }
    }
    const AI_IMAGE_MODEL_CFG = {
      'gpt-image-2': {
        label: 'GPT-image2.0',
        sizes: ['auto', '1024x1024', '1536x1024', '1024x1536'],
        defaultSize: '1024x1024',
        cost: '≈0.03元'
      },
      'rh_gpt_image_i2i': {
        label: 'RH gpt低价',
        resolutions: ['1k', '2k', '4k'],
        defaultRes: '1k',
        aspectRatios: ['9:16', '16:9', '1:1', '4:3', '3:4', '3:2', '2:3', '5:4', '4:5', '21:9'],
        defaultAspect: '9:16',
        cost: 'RH 低价版'
      },
      'nano_banana_pro': {
        label: 'Nano Banana Pro',
        resolutions: ['1k', '2k', '4k'],
        defaultRes: '1k',
        aspectRatios: ['9:16', '16:9', '1:1', '4:3', '3:4', '4:5'],
        defaultAspect: '9:16',
        cost: 'Nano Banana Pro'
      },
      'nano_banana_2': {
        label: 'Nano Banana 2.0',
        resolutions: ['1k', '2k', '4k'],
        defaultRes: '1k',
        aspectRatios: ['9:16', '16:9', '1:1', '4:3', '3:4', '4:5'],
        defaultAspect: '9:16',
        cost: 'Nano Banana 2.0'
      },
      'rh_gpt_image_official': {
        label: 'RH gpt稳定版',
        resolutions: ['1k', '2k', '4k'],
        defaultRes: '2k',
        aspectRatios: ['1:1','1:2','2:1','1:3','3:1','2:3','3:2','3:4','4:3','4:5','5:4','9:16','21:9','9:21','16:9'],
        defaultAspect: '9:16',
        qualities: ['low', 'medium', 'high'],
        defaultQuality: 'medium',
        cost: 'RH 稳定版'
      },
      'flux_klein_9b': {
        label: 'FLUX Klein 9B',
        aspectRatios: ['1:1','3:4','4:3','9:16','16:9','2:3','3:2','auto'],
        defaultAspect: '1:1',
        cost: 'FLUX.2 Klein 9B 编辑'
      },
      'seedream_v4': {
        label: 'Seedream V4',
        resolutions: ['1k', '2k', '4k'],
        defaultRes: '2k',
        cost: 'Seedream V4 图生图'
      },
      'seedream_v5_lite': {
        label: 'Seedream V5 Lite',
        resolutions: ['2k', '3k'],
        defaultRes: '2k',
        cost: 'Seedream V5 Lite 图生图'
      },
      'midjourney_v7': {
        label: 'Midjourney V7',
        aspectRatios: ['auto','1:1','16:9','16:10','4:3','3:2','9:16','10:16','3:4','2:3'],
        defaultAspect: '3:4',
        mjVersions: ['Midjourney V7','Midjourney V6.1','Midjourney V6','Midjourney V5.2','Midjourney V5.1','Niji V5','Niji V6'],
        defaultMjVersion: 'Midjourney V7',
        cost: 'MJ V7 文生图'
      },
      'flux2': {
        label: 'FLUX2 图生图',
        aspectRatios: ['1:1','9:16','16:9','4:3','3:4','3:2','2:3'],
        defaultAspect: '9:16',
        cost: 'FLUX2 图生图'
      },
      'krea2': {
        label: 'Krea2 满血版',
        aspectRatios: ['1:1 (Square)','2:3 (Portrait Photo)','3:2 (Photo)','3:4 (Portrait Standard)','4:3 (Standard)','9:16 (Portrait Widescreen)','16:9 (Widescreen)','21:9 (Ultrawide)'],
        defaultAspect: '9:16 (Portrait Widescreen)',
        cost: 'Krea2 文生图'
      }
    };
    function removeNode(id) {
      pushHistory();
      canvasData.connections = canvasData.connections.filter(c => c.from !== id && c.to !== id);
      canvasData.nodes = canvasData.nodes.filter(n => n.id !== id);
      if (nodeElements[id]) { nodeElements[id].remove(); delete nodeElements[id]; }
      if (selectedNode === id) { selectedNode = null; updateRunSelectedBtn(); }
      if (selectedNodes.has(id)) { selectedNodes.delete(id); updateRunSelectedBtn(); }
      stopPolling(id);
      renderConnections();
      updateStatusbar();
      autoSave();
    }
    function clearCanvas() {
      pushHistory();
      canvasData.nodes.forEach(n => stopPolling(n.id));
      canvasData = { nodes: [], connections: [] };
      Object.values(nodeElements).forEach(el => el.remove());
      Object.keys(nodeElements).forEach(k => delete nodeElements[k]);
      selectedNode = null; currentCanvasId = null; activeCanvasId = null;
      clearBoxSelection();
      renderConnections(); updateStatusbar();
      localStorage.removeItem('autosave');
    }

    function getChainNodeIds(nodeId) {
      const chain = new Set([nodeId]);
      const queue = [nodeId];
      while (queue.length) {
        const nid = queue.shift();
        for (const c of canvasData.connections) {
          if (c.to === nid && !chain.has(c.from)) { chain.add(c.from); queue.push(c.from); }
          if (c.from === nid && !chain.has(c.to)) { chain.add(c.to); queue.push(c.to); }
        }
      }
      return chain;
    }
    function getUpstreamNodeIds(nodeId) {
      return canvasData.connections.filter(c => c.to === nodeId).map(c => c.from);
    }
    // 获取连到指定目标端口的 upstream 信息 { node, fromField, conn }
    function getUpstreamByPort(nodeId, toField) {
      const conns = canvasData.connections.filter(c => c.to === nodeId);
      if (conns.length === 0) return null;
      // 优先按 toField 精确匹配
      const conn = conns.find(c => c.toField === toField);
      if (conn) {
        const node = canvasData.nodes.find(n => n.id === conn.from);
        return node ? { node, fromField: conn.fromField, conn } : null;
      }
      // 兼容旧连线（无 toField）：仅当所有连线都无 toField 时 fallback 到第一条
      if (conns.every(c => !c.toField)) {
        const fallback = conns[0];
        const node = canvasData.nodes.find(n => n.id === fallback.from);
        return node ? { node, fromField: fallback.fromField, conn: fallback } : null;
      }
      return null; // 有带 toField 的连线但不匹配此端口 → 无上游
    }
    function findBlockingUpstreams(nodeIds) {
      const blocking = [];
      const checked = new Set();
      for (const nid of nodeIds) {
        for (const uid of getUpstreamNodeIds(nid)) {
          if (checked.has(uid)) continue;
          checked.add(uid);
          const rt = nodeRuntime[uid];
          if (!rt || rt.status !== 'success') {
            const n = canvasData.nodes.find(x => x.id === uid);
            blocking.push({ id: uid, title: n ? (NODE_CFG[n.type]?.title || n.type) : uid });
          }
        }
      }
      return blocking;
    }
    function cloneChain() {
      if (!selectedNode) { showToast('请先选中一条链路中的任意节点'); return; }
      pushHistory();
      const chainNodes = getChainNodeIds(selectedNode);
      // 克隆节点
      const idMap = {};
      const offsetX = 40, offsetY = 40;
      for (const nid of chainNodes) {
        const old = canvasData.nodes.find(n => n.id === nid);
        if (!old) continue;
        const newId = uid();
        idMap[nid] = newId;
        const newNode = {
          id: newId,
          type: old.type,
          x: old.x + offsetX,
          y: old.y + offsetY,
          data: JSON.parse(JSON.stringify(old.data))
        };
        // 清除运行状态
        delete newNode.data._error;
        canvasData.nodes.push(newNode);
        renderNode(newNode);
      }
      // 克隆连线
      for (const c of canvasData.connections) {
        if (chainNodes.has(c.from) && chainNodes.has(c.to)) {
          canvasData.connections.push({
            id: uid(),
            from: idMap[c.from],
            to: idMap[c.to],
            fromField: c.fromField,
            toField: c.toField
          });
        }
      }
      renderConnections();
      updateStatusbar();
      autoSave();
    }

    // ═══════════════════════════════════════════════════════════════
    // 节点渲染
    // ═══════════════════════════════════════════════════════════════
    function renderNode(node) {
      const cfg = NODE_CFG[node.type] || { icon:null, title:node.type, color:'#555' };
      const el = document.createElement('div');
      let cls = 'node';
      if (node.type === 'gpt_image') cls += ' gen-node';
      if (node.type === 'seedance_video') cls += ' video-node';
      if (selectedNodes.has(node.id)) cls += ' box-selected';
      el.className = cls;
      el.style.left = node.x + 'px'; el.style.top = node.y + 'px';
      el.style.setProperty('--node-color', cfg.color);
      el.dataset.id = node.id;
      el.innerHTML = buildNodeHTML(node, cfg);
      document.getElementById('nodes-layer').appendChild(el);
      nodeElements[node.id] = el;
      bindNodeEvents(el, node);
      scheduleMinimap();
      return el;
    }
    function buildNodeHTML(node, cfg) {
      const ports = NODE_PORTS[node.type] || { inputs: [], outputs: [] };
      const inputs = ports.inputs || [];
      const outputs = ports.outputs || [];
      const inPorts = inputs.map((p, i) =>
        `<div class="port port-in" data-port="in" data-portname="${p.name}" data-porttype="${p.type}"
             style="--port-index:${i};--port-count:${inputs.length}">
          <span class="port-label">${p.label}</span>
        </div>`
      ).join('');
      const outPorts = outputs.map((p, i) =>
        `<div class="port port-out" data-port="out" data-portname="${p.name}" data-porttype="${p.type}"
             style="--port-index:${i};--port-count:${outputs.length}">
          <span class="port-label">${p.label}</span>
        </div>`
      ).join('');
      const iconSvg = cfg.icon ? `<svg class="node-icon-svg"><use href="#icon-${cfg.icon}"/></svg>` : '';
      const rt = nodeRuntime[node.id] || {};
      const status = rt.status || 'idle';
      const label = STATUS_LABELS[status] || '待机';
      return `${inPorts}${outPorts}
        <button class="node-delete" onclick="event.stopPropagation();removeNode('${node.id}')" title="删除节点">✕</button>
        <div class="node-title-float" data-role="drag">
          <span class="node-icon">${iconSvg}</span>
          <span class="node-title">${cfg.title}</span>
          <span class="node-id">#${node.id.slice(0,6)}</span>
        </div>
        <div class="node-status-float">
          <span class="node-badge ${status}" id="badge-${node.id}">${label}</span>
        </div>
        <div class="node-preview-layer" data-role="preview">${buildNodePreview(node)}</div>
        <div class="node-meta-float">${buildNodeMeta(node)}</div>
        <div class="node-progress-bar"><div class="fill" id="prog-${node.id}" style="width:0%"></div></div>`;
    }
    // 端口类型映射（用于配色）
    function portTypeFor(nodeType, dir) {
      const ports = NODE_PORTS[nodeType];
      if (!ports) return 'IMAGE';
      const list = dir === 'out' ? ports.outputs : ports.inputs;
      if (list && list.length) return list[0].type;
      return 'IMAGE';
    }
    // 预览层：仅保留图片/视频/占位；无参数控件
    function buildNodePreview(node) {
      const d = node.data;
      // mask_edit 特殊：底图 + 遮罩叠加
      if (node.type === 'mask_edit') {
        let baseUrl = d.image_url || '';
        if (!baseUrl) {
          const up = getUpstreamByPort(node.id, 'image');
          if (up) baseUrl = (nodeRuntime[up.node.id]?.image_url) || up.node.data.image_url || '';
        }
        if (baseUrl || d.mask_url) {
          return `<div class="mask-stack">
            ${baseUrl ? `<img class="mask-base" src="${baseUrl}"/>` : ''}
            ${d.mask_url ? `<img class="mask-overlay" src="${d.mask_url}"/>` : ''}
            <div class="mask-hint">${d.mask_url ? '双击可重新编辑遮罩' : '双击开始绘制遮罩'}</div>
            ${buildPreviewTools(d.mask_url || baseUrl)}
          </div>`;
        }
        return `<div class="preview-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 20l9-9-9-9-9 9 9 9zM12 4v16"/></svg>
          <span>请连线上游图片</span>
          <span class="empty-hint">双击开始绘制遮罩</span>
        </div>`;
      }
      // 视频节点：优先视频，其次首帧
      if (node.type === 'seedance_video') {
        if (d.video_url) {
          return `<video src="${d.video_url}" muted playsinline preload="metadata"></video>
            ${buildPreviewTools(d.video_url, true)}`;
        }
        const firstFrame = d.first_frame || d.image_url;
        if (firstFrame) {
          return `<img src="${firstFrame}"/>${buildPreviewTools(firstFrame)}`;
        }
        return `<div class="preview-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <rect x="3" y="6" width="18" height="12" rx="2"/><path d="M10 9l5 3-5 3z"/></svg>
          <span>视频生成</span>
          <span class="empty-hint">点击节点编辑参数</span>
        </div>`;
      }
      // 通用图片预览
      if (d.image_url) {
        return `<img src="${d.image_url}"/>${buildPreviewTools(d.image_url)}`;
      }
      // 失败态：显示错误信息
      if (d._error) {
        const errMatch = d._error.match(/^\[([A-Z]\d+)\]\s*(.+?):\s*/);
        const errCode = errMatch ? errMatch[1] : '';
        const errLabel = errMatch ? errMatch[2] : '';
        const errDetail = errMatch ? d._error.slice(errMatch[0].length) : d._error;
        return `<div class="preview-empty" style="color:var(--danger);">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>
          <span style="font-weight:600;">${errCode ? errCode + ' ' : ''}生成失败</span>
          ${errLabel ? `<span class="empty-hint" style="color:var(--danger);opacity:0.8;">${errLabel}</span>` : ''}
          <span class="empty-hint" style="max-width:200px;word-break:break-all;opacity:0.6;">${errDetail.substring(0, 80)}${errDetail.length > 80 ? '...' : ''}</span>
        </div>`;
      }
      // 空态
      const emptyHint = node.type === 'image_input' ? '点击节点上传图片'
        : node.type === 'gpt_image' ? '点击节点编辑参数并运行'
        : node.type === 'remove_bg' ? '连线上游后运行'
        : '点击节点编辑参数';
      return `<div class="preview-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <circle cx="9" cy="9" r="2"/><path d="M21 15l-5-5-9 9"/></svg>
        <span>${NODE_CFG[node.type]?.title || node.type}</span>
        <span class="empty-hint">${emptyHint}</span>
      </div>`;
    }
    // 预览工具栏（悬浮在预览层右上角）：预览大图 + 下载
    function buildPreviewTools(url, isVideo=false) {
      if (!url) return '';
      const safe = url.replace(/'/g, "\\'");
      return `<div class="preview-tools">
        <button class="pv-tool" title="放大预览" onclick="event.stopPropagation();openLightbox('${safe}',${isVideo?'true':'false'})">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/><path d="M11 8v6M8 11h6"/></svg>
        </button>
        <button class="pv-tool" title="下载" onclick="event.stopPropagation();downloadAsset('${safe}')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </button>
      </div>`;
    }
    // 下载资源
    function downloadAsset(url) {
      const a = document.createElement('a');
      a.href = url;
      // 提取文件名
      try {
        const u = new URL(url, location.origin);
        const name = u.pathname.split('/').pop() || 'download';
        a.download = name;
      } catch(_) { a.download = 'download'; }
      a.target = '_blank';
      a.rel = 'noopener';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    window.downloadAsset = downloadAsset;
    // 元信息浮层：显示节点关键属性
    function buildNodeMeta(node) {
      const d = node.data;
      const parts = [];
      if (d._width && d._height) {
        parts.push(`<span class="meta-val">${d._width}×${d._height}</span>`);
      }
      if (node.type === 'gpt_image') {
        const model = d.model || 'gpt-image-2';
        parts.push(`<span class="meta-val">${model}</span>`);
        const size = d.size || d.resolution || '';
        const ar = d.aspect_ratio || '';
        if (size) parts.push(`<span class="meta-key">size:</span><span class="meta-val">${size}</span>`);
        else if (ar) parts.push(`<span class="meta-key">ar:</span><span class="meta-val">${ar}</span>`);
      } else if (node.type === 'seedance_video') {
        const channel = d.channel || 'official';
        const ar = d.aspect_ratio || '9:16';
        const dur = d.duration || '5';
        parts.push(`<span class="meta-val">${channel}</span>`);
        parts.push(`<span class="meta-val">${ar}</span>`);
        parts.push(`<span class="meta-val">${dur}s</span>`);
      }
      if (parts.length === 0) return '&nbsp;';
      return parts.join('<span class="meta-dot">·</span>');
    }
    // 旧 buildNodeBody 已废弃：节点不再内嵌参数栏，所有参数移至底部浮层参数面板
    function buildNodeBody(_node) { return ''; }
    function updateNodeData(id, field, val) {
      const n = canvasData.nodes.find(n=>n.id===id);
      if (!n) return;
      n.data[field] = val;
      autoSave();
      // 参数变化时同步刷新元信息浮层（如 model / channel / ratio）
      const el = nodeElements[id];
      if (el) {
        const metaEl = el.querySelector('.node-meta-float');
        if (metaEl) metaEl.innerHTML = buildNodeMeta(n);
      }
    }
    function migrateNodeData(node) {
      const legacyModelByType = {
        rh_gpt_image_i2i: 'rh_gpt_image_i2i',
        nano_banana_pro: 'nano_banana_pro',
        nano_banana_2: 'nano_banana_2'
      };
      if (legacyModelByType[node.type]) {
        node.data = node.data || {};
        node.data.model = legacyModelByType[node.type];
        node.type = 'gpt_image';
      }
      if (node.type !== 'gpt_image' || !node.data) return;
      // 旧字段 ratio → aspect_ratio
      if (node.data.ratio && !node.data.aspect_ratio) {
        node.data.aspect_ratio = node.data.ratio;
        delete node.data.ratio;
      }
      // 旧 model 选项清理
      if (node.data.model === 'gpt-image-2-official') {
        node.data.model = 'gpt-image-2';
      }
      if (!AI_IMAGE_MODEL_CFG[node.data.model]) node.data.model = 'gpt-image-2';
      const cfg = AI_IMAGE_MODEL_CFG[node.data.model];
      if (node.data.prompt == null) node.data.prompt = '';
      if (node.data.hair_url == null) node.data.hair_url = '';
      if (node.data.makeup == null) node.data.makeup = '';
      if (node.data.clothing_url == null) node.data.clothing_url = '';
      if (node.data.image2_url == null) node.data.image2_url = '';
      if (node.data.image3_url == null) node.data.image3_url = '';
      if (node.data.image4_url == null) node.data.image4_url = '';
      if (node.data.model === 'gpt-image-2') {
        if (node.data.resolution && !node.data.size) node.data.size = node.data.resolution;
        if (!cfg.sizes.includes(node.data.size)) node.data.size = cfg.defaultSize;
        return;
      }
      if (!cfg.resolutions || !cfg.resolutions.includes(node.data.resolution)) node.data.resolution = cfg.defaultRes;
      if (!cfg.aspectRatios || !cfg.aspectRatios.includes(node.data.aspect_ratio)) node.data.aspect_ratio = cfg.defaultAspect;
    }
    function refreshNodeBody(nodeId) {
      // 新架构：不再有内嵌 body，改为刷新预览层 + 元信息 + 参数面板
      refreshNodePreview(nodeId);
      autoSave();
    }
    function setNodeModel(nodeId, model) {
      const node = canvasData.nodes.find(n => n.id === nodeId);
      if (!node) return;
      const cfg = AI_IMAGE_MODEL_CFG[model] || AI_IMAGE_MODEL_CFG['gpt-image-2'];
      node.data.model = model;
      if (model === 'gpt-image-2') {
        if (node.data.resolution && !node.data.size) node.data.size = node.data.resolution;
        if (!cfg.sizes.includes(node.data.size)) node.data.size = cfg.defaultSize;
      } else {
        if (cfg.aspectRatios && !cfg.aspectRatios.includes(node.data.aspect_ratio)) {
          node.data.aspect_ratio = cfg.defaultAspect;
        }
        if (cfg.resolutions && !cfg.resolutions.includes(node.data.resolution)) {
          node.data.resolution = cfg.defaultRes;
        }
        if (cfg.mjVersions && (!node.data.mj_version || !cfg.mjVersions.includes(node.data.mj_version))) {
          node.data.mj_version = cfg.defaultMjVersion;
        }
      }
      refreshNodeBody(nodeId);
    }
    function updateCharCount(el) {
      const box = el.parentElement;
      const cnt = box.querySelector('.gen-char-count');
      if (cnt) cnt.textContent = el.value.length + ' / 2500';
    }
    function getDefaultImagePrompt() {
      return '以图一人物作为唯一主体。\n保持图一人物的：\n五官、脸型、骨相、眼睛形状、鼻子、嘴唇厚度、肤色、年龄感、气质完全不变。\n仅参考图二的穿搭风格。';
    }
    function getDefaultVideoPrompt() {
      return '基于原图生成一段自然动态视频。人物保持五官不变，动作流畅，光影自然，背景协调。';
    }
    async function polishPrompt(nodeId) {
      const node = canvasData.nodes.find(n => n.id === nodeId);
      if (!node) return;
      const base = node.data.prompt || getDefaultImagePrompt();
      const p = base + '\n\n请优化：使用更具体的摄影与光影描述，增强画面质感与商业海报表现力。';
      node.data.prompt = p;
      refreshNodePreview(nodeId);
      autoSave();
    }
    function refreshNodePreview(id) {
      const node = canvasData.nodes.find(n=>n.id===id); if(!node) return;
      const el = nodeElements[id]; if(!el) return;
      // 更新预览层
      const previewEl = el.querySelector('.node-preview-layer');
      if (previewEl) previewEl.innerHTML = buildNodePreview(node);
      // 更新元信息
      const metaEl = el.querySelector('.node-meta-float');
      if (metaEl) metaEl.innerHTML = buildNodeMeta(node);
      // 如果当前参数面板打开的是本节点，同步刷新面板
      if (paramsPanelNodeId === id) renderParamsPanel();
    }

    // ═══════════════════════════════════════════════════════════════
    // 图片上传
    // ═══════════════════════════════════════════════════════════════
    async function uploadImage(nodeId, input) {
      const file = input.files[0]; if(!file) return;
      const fd = new FormData(); fd.append('file', file);
      try {
        const r = await _apiFetch('/api/assets/upload', { method:'POST', body:fd });
        const d = await r.json();
        const node = canvasData.nodes.find(n=>n.id===nodeId);
        if (node) { node.data.image_url = d.url; refreshNodePreview(nodeId); autoSave(); }
      } catch(e) { showToast('上传失败: '+e.message); }
    }
    async function uploadRefImage(nodeId, field, input) {
      const file = input.files[0]; if(!file) return;
      const fd = new FormData(); fd.append('file', file);
      try {
        const r = await _apiFetch('/api/assets/upload', { method:'POST', body:fd });
        const d = await r.json();
        const node = canvasData.nodes.find(n=>n.id===nodeId);
        if (node) { node.data[field] = d.url; refreshNodePreview(nodeId); autoSave(); }
      } catch(e) { showToast('上传失败: '+e.message); }
      input.value = '';
    }
    function clearNodeField(nodeId, field) {
      const node = canvasData.nodes.find(n => n.id === nodeId);
      if (!node) return;
      node.data[field] = '';
      refreshNodePreview(nodeId);
      autoSave();
      if (paramsPanelNodeId === nodeId) renderParamsPanel();
    }

    // ═══════════════════════════════════════════════════════════════
    // 遮罩编辑器
    // ═══════════════════════════════════════════════════════════════
    let maskEditorNodeId = null;
    let maskCtx = null;
    let maskDrawing = false;
    let maskEraser = false;
    let maskImage = null;
    let maskPaintCanvas = null; // 离屏画布：仅保存红色涂抹层

    function openMaskEditor(nodeId) {
      const node = canvasData.nodes.find(n => n.id === nodeId);
      if (!node) return;
      let imageUrl = node.data.image_url;
      if (!imageUrl) {
        const up = getUpstreamByPort(nodeId, 'image');
        if (up) imageUrl = (nodeRuntime[up.node.id]?.image_url) || up.node.data.image_url;
      }
      if (!imageUrl) { showToast('请先连线上游图片输入节点'); return; }
      maskEditorNodeId = nodeId;
      maskEraser = false;
      const eraserBtn = document.getElementById('eraser-btn');
      if (eraserBtn) eraserBtn.style.background = '';
      document.getElementById('mask-editor-modal').style.display = 'flex';
      const canvas = document.getElementById('mask-canvas');
      maskCtx = canvas.getContext('2d');
      maskImage = new Image();
      maskImage.crossOrigin = 'anonymous';
      maskImage.onload = () => {
        canvas.width = maskImage.width;
        canvas.height = maskImage.height;
        maskPaintCanvas = document.createElement('canvas');
        maskPaintCanvas.width = maskImage.width;
        maskPaintCanvas.height = maskImage.height;
        const maxW = window.innerWidth * 0.8, maxH = window.innerHeight * 0.65;
        const scale = Math.min(maxW / maskImage.width, maxH / maskImage.height, 1);
        canvas.style.width = (maskImage.width * scale) + 'px';
        canvas.style.height = (maskImage.height * scale) + 'px';
        compositeMask();
        if (node.data.mask_url) {
          const existingMask = new Image();
          existingMask.crossOrigin = 'anonymous';
          existingMask.onload = () => {
            const tmpC = document.createElement('canvas');
            tmpC.width = maskImage.width; tmpC.height = maskImage.height;
            const tctx = tmpC.getContext('2d');
            tctx.drawImage(existingMask, 0, 0);
            const mData = tctx.getImageData(0, 0, tmpC.width, tmpC.height).data;
            const pctx = maskPaintCanvas.getContext('2d');
            const oData = pctx.createImageData(tmpC.width, tmpC.height);
            const od = oData.data;
            for (let i = 0; i < mData.length; i += 4) {
              if (mData[i+3] < 128) {
                od[i] = 236; od[i+1] = 72; od[i+2] = 153; od[i+3] = 128;
              }
            }
            pctx.putImageData(oData, 0, 0);
            compositeMask();
          };
          existingMask.src = node.data.mask_url;
        }
      };
      maskImage.src = imageUrl;
    }

    function compositeMask() {
      if (!maskCtx || !maskImage) return;
      maskCtx.clearRect(0, 0, maskCtx.canvas.width, maskCtx.canvas.height);
      maskCtx.drawImage(maskImage, 0, 0);
      if (maskPaintCanvas) maskCtx.drawImage(maskPaintCanvas, 0, 0);
    }

    function redrawMask() { compositeMask(); }

    function closeMaskEditor() {
      document.getElementById('mask-editor-modal').style.display = 'none';
      maskEditorNodeId = null;
      maskDrawing = false;
    }

    function toggleEraser() {
      maskEraser = !maskEraser;
      const btn = document.getElementById('eraser-btn');
      if (btn) btn.style.background = maskEraser ? 'rgba(236,72,153,0.2)' : '';
    }

    function clearMask() {
      if (!maskPaintCanvas) return;
      const pctx = maskPaintCanvas.getContext('2d');
      pctx.clearRect(0, 0, maskPaintCanvas.width, maskPaintCanvas.height);
      compositeMask();
    }

    function getMaskPos(e) {
      const canvas = document.getElementById('mask-canvas');
      const r = canvas.getBoundingClientRect();
      const sx = canvas.width / r.width, sy = canvas.height / r.height;
      return { x: (e.clientX - r.left) * sx, y: (e.clientY - r.top) * sy };
    }

    function startMaskDraw(e) {
      maskDrawing = true;
      drawMask(e);
    }

    function drawMask(e) {
      if (!maskDrawing || !maskCtx || !maskPaintCanvas) return;
      const pos = getMaskPos(e);
      const size = parseInt(document.getElementById('brush-size').value);
      const pctx = maskPaintCanvas.getContext('2d');
      if (maskEraser) {
        pctx.save();
        pctx.globalCompositeOperation = 'destination-out';
        pctx.beginPath();
        pctx.arc(pos.x, pos.y, size, 0, Math.PI * 2);
        pctx.fillStyle = 'rgba(0,0,0,1)';
        pctx.fill();
        pctx.restore();
      } else {
        pctx.fillStyle = 'rgba(236,72,153,0.5)';
        pctx.beginPath();
        pctx.arc(pos.x, pos.y, size, 0, Math.PI * 2);
        pctx.fill();
      }
      compositeMask();
    }

    function stopMaskDraw() {
      maskDrawing = false;
    }

    async function saveMask() {
      if (!maskPaintCanvas || !maskEditorNodeId) return;
      const pctx = maskPaintCanvas.getContext('2d');
      const pData = pctx.getImageData(0, 0, maskPaintCanvas.width, maskPaintCanvas.height).data;
      const tmp = document.createElement('canvas');
      tmp.width = maskPaintCanvas.width;
      tmp.height = maskPaintCanvas.height;
      const tctx = tmp.getContext('2d');
      const maskData = tctx.createImageData(tmp.width, tmp.height);
      const md = maskData.data;
      for (let i = 0; i < pData.length; i += 4) {
        if (pData[i+3] > 10) {
          md[i] = 0; md[i+1] = 0; md[i+2] = 0; md[i+3] = 0;
        } else {
          md[i] = 0; md[i+1] = 0; md[i+2] = 0; md[i+3] = 255;
        }
      }
      tctx.putImageData(maskData, 0, 0);
      tmp.toBlob(async (blob) => {
        const fd = new FormData();
        fd.append('file', blob, 'mask.png');
        try {
          const resp = await _apiFetch('/api/assets/upload', { method: 'POST', body: fd });
          const d = await resp.json();
          const node = canvasData.nodes.find(n => n.id === maskEditorNodeId);
          if (node) {
            node.data.mask_url = d.url;
            refreshNodePreview(maskEditorNodeId);
            autoSave();
          }
          closeMaskEditor();
        } catch(e) { showToast('遮罩上传失败: ' + e.message); }
      }, 'image/png');
    }

    // 绑定 canvas 涂抹事件（一次性）
    (function() {
      const c = document.getElementById('mask-canvas');
      c.addEventListener('mousedown', startMaskDraw);
      c.addEventListener('mousemove', drawMask);
      c.addEventListener('mouseup', stopMaskDraw);
      c.addEventListener('mouseleave', stopMaskDraw);
    })();

    // ═══════════════════════════════════════════════════════════════
    // 连线渲染（SVG 贝塞尔曲线）
    // ═══════════════════════════════════════════════════════════════
    function getDefaultPortName(nodeType, dir) {
      const ports = NODE_PORTS[nodeType];
      if (!ports) return null;
      const list = dir === 'out' ? ports.outputs : ports.inputs;
      return list && list.length ? list[0].name : null;
    }
    function renderConnections() {
      const svg = document.getElementById('svg-layer');
      const temp = svg.querySelector('.conn-temp');
      svg.innerHTML = '';
      if (temp) svg.appendChild(temp);
      for (const conn of canvasData.connections) {
        const fn = canvasData.nodes.find(n=>n.id===conn.from);
        const tn = canvasData.nodes.find(n=>n.id===conn.to);
        if (!fn || !tn) continue;
        const fe = nodeElements[conn.from], te = nodeElements[conn.to];
        if (!fe || !te) continue;
        // 兼容旧数据：无 fromField/toField 时取默认第一个端口
        const fromField = conn.fromField || getDefaultPortName(fn.type, 'out');
        const toField = conn.toField || getDefaultPortName(tn.type, 'in');
        const fromPort = fromField ? fe.querySelector(`.port-out[data-portname="${fromField}"]`) : null;
        const toPort = toField ? te.querySelector(`.port-in[data-portname="${toField}"]`) : null;
        const start = getPortCenter(fn, fe, fromPort, 'out');
        const end = getPortCenter(tn, te, toPort, 'in');
        const dx = Math.max(60, Math.abs(end.x-start.x)*0.45);
        const p = `M ${start.x} ${start.y} C ${start.x+dx} ${start.y}, ${end.x-dx} ${end.y}, ${end.x} ${end.y}`;
        const el = document.createElementNS('http://www.w3.org/2000/svg','path');
        el.setAttribute('d', p);
        let cls = 'conn-path';
        if (selectedConn === conn.id) cls += ' selected';
        // 根据上游节点运行状态自动着色
        const fromRt = nodeRuntime[conn.from];
        if (fromRt) {
          if (fromRt.status === 'running' || fromRt.status === 'pending') cls += ' running';
          else if (fromRt.status === 'success') cls += ' success';
          else if (fromRt.status === 'failed' || fromRt.status === 'blocked' || fromRt.status === 'interrupted') cls += ' failed';
        }
        el.setAttribute('class', cls);
        el.dataset.connId = conn.id;
        el.addEventListener('click', (e) => { e.stopPropagation(); selectedConn = conn.id; renderConnections(); });
        svg.appendChild(el);
      }
      scheduleMinimap();
    }

    // ═══════════════════════════════════════════════════════════════
    // 节点交互
    // ═══════════════════════════════════════════════════════════════
    function bindNodeEvents(el, node) {
      const dragHandle = el.querySelector('.node-title-float');
      if (dragHandle) {
        dragHandle.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        e.stopPropagation();
        if (e.shiftKey) { toggleNodeBoxSelection(node.id); return; }
        selectedNode = node.id;
        clearBoxSelection();
        updateRunSelectedBtn();
        document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
        el.classList.add('selected', 'dragging');
        const sx = e.clientX, sy = e.clientY, ox = node.x, oy = node.y;
        const snapBefore = snapshotCanvas();
        let moved = false;
        function mv(ev) {
          node.x = ox + (ev.clientX-sx)/viewScale;
          node.y = oy + (ev.clientY-sy)/viewScale;
          if (!moved && (node.x !== ox || node.y !== oy)) moved = true;
          el.style.left = node.x+'px'; el.style.top = node.y+'px';
          const aff = canvasData.connections.filter(c=>c.from===node.id||c.to===node.id);
          if (aff.length) renderConnections();
          // 参数面板跟随当前拖拽节点
          if (paramsPanelNodeId === node.id) positionParamsPanel();
        }
        function up() {
          el.classList.remove('dragging');
          document.removeEventListener('mousemove', mv);
          document.removeEventListener('mouseup', up);
          if (moved) {
            undoStack.push(snapBefore);
            if (undoStack.length > MAX_HISTORY) undoStack.shift();
            redoStack = [];
            updateUndoRedoButtons();
          }
          autoSave();
        }
        document.addEventListener('mousemove', mv);
        document.addEventListener('mouseup', up);
        });
      }
      const outPorts = el.querySelectorAll('.port-out');
      outPorts.forEach(p => {
        p.addEventListener('mousedown', (e) => {
          e.stopPropagation(); e.preventDefault();
          isConnecting = true;
          connStart = { nodeId: node.id, portName: p.dataset.portname };
        });
      });
      // 节点主体点击：选中 + 打开参数面板
      el.addEventListener('mousedown', (e) => {
        if (e.target.classList.contains('port') || e.target.closest('.node-title-float')) return;
        if (e.target.closest('.node-delete') || e.target.closest('.pv-tool')) return;  // 删除/预览工具按钮
        if (e.shiftKey) { e.stopPropagation(); e.preventDefault(); toggleNodeBoxSelection(node.id); return; }
        selectedNode = node.id;
        clearBoxSelection();
        updateRunSelectedBtn();
        document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
        el.classList.add('selected');
      });
      // 单击（不拖拽时）：打开参数面板
      el.addEventListener('click', (e) => {
        if (e.target.closest('.port') || e.target.closest('.node-delete')) return;
        if (e.target.closest('.pv-tool')) return;   // 预览工具栏点击不弹参数面板
        openParamsPanel(node.id);
      });
      // 双击：打开参数面板并聚焦第一个字段（mask_edit 特殊 → 遮罩编辑器）
      el.addEventListener('dblclick', (e) => {
        if (e.target.closest('.port') || e.target.closest('.node-delete') || e.target.closest('.pv-tool')) return;
        if (node.type === 'mask_edit') {
          e.stopPropagation();
          openMaskEditor(node.id);
        } else {
          openParamsPanel(node.id, true);
        }
      });
    }

    // ═══════════════════════════════════════════════════════════════
    // 底部浮层参数面板（点击节点弹出，Figma / VSCode 风格）
    // ═══════════════════════════════════════════════════════════════
    let paramsPanelNodeId = null;
    let paramsPanelEl = null;

    function ensureParamsPanel() {
      if (paramsPanelEl) return paramsPanelEl;
      paramsPanelEl = document.createElement('div');
      paramsPanelEl.id = 'node-params-panel';
      // 挂到 body，避免受 workspace transform/scale 影响，保证 select 下拉正常
      document.body.appendChild(paramsPanelEl);
      return paramsPanelEl;
    }

    // 计算并应用参数面板的位置：贴在目标节点卡片下方
    function positionParamsPanel() {
      if (!paramsPanelEl || !paramsPanelNodeId) return;
      const el = nodeElements[paramsPanelNodeId];
      if (!el) return;
      // 面板挂到 body，位置使用节点在视口中的实际坐标
      const rect = el.getBoundingClientRect();
      const gap = 18;
      paramsPanelEl.style.left = (rect.left + rect.width / 2 - 260) + 'px';   // 面板宽 520，居中于节点
      paramsPanelEl.style.top  = (rect.bottom + gap) + 'px';
    }

    function openParamsPanel(nodeId, focusFirst=false) {
      const node = canvasData.nodes.find(n => n.id === nodeId);
      if (!node) return;
      paramsPanelNodeId = nodeId;
      const panel = ensureParamsPanel();
      renderParamsPanel();
      positionParamsPanel();
      panel.classList.add('open');
      if (focusFirst) {
        setTimeout(() => {
          const first = panel.querySelector('textarea, input[type="text"], select');
          if (first) first.focus();
        }, 240);
      }
    }

    function closeParamsPanel() {
      if (paramsPanelEl) paramsPanelEl.classList.remove('open');
      paramsPanelNodeId = null;
    }

    function togglePpGroup(headerEl) {
      const g = headerEl.closest('.pp-group');
      if (g) g.classList.toggle('collapsed');
    }
    window.togglePpGroup = togglePpGroup;
    window.openParamsPanel = openParamsPanel;
    window.closeParamsPanel = closeParamsPanel;

    // 渲染当前 paramsPanelNodeId 对应节点的参数
    function renderParamsPanel() {
      if (!paramsPanelEl || !paramsPanelNodeId) return;
      const node = canvasData.nodes.find(n => n.id === paramsPanelNodeId);
      if (!node) { closeParamsPanel(); return; }
      const cfg = NODE_CFG[node.type] || { icon: null, title: node.type, color: '#666' };
      paramsPanelEl.style.setProperty('--node-color', cfg.color);
      const iconSvg = cfg.icon ? `<svg><use href="#icon-${cfg.icon}"/></svg>` : '';
      const rt = nodeRuntime[node.id] || {};
      const status = rt.status || 'idle';
      const statusLabel = STATUS_LABELS[status] || '待机';
      paramsPanelEl.innerHTML = `
        <div class="pp-header">
          <span class="pp-title">
            <span class="pp-icon">${iconSvg}</span>
            ${cfg.title}
          </span>
          <span class="pp-subtitle">#${node.id.slice(0,6)} · ${statusLabel}</span>
          <div class="pp-actions">
            <button class="pp-btn primary" onclick="runNodeFromPanel('${node.id}')">▶ 运行</button>
            <button class="pp-btn" onclick="closeParamsPanel()" title="关闭 (Esc)">✕</button>
          </div>
        </div>
        ${status === 'failed' && node.data._error ? `
        <div class="pp-error-bar">
          <span class="pp-error-code">${(node.data._error.match(/^\[([A-Z]\d+)\]/) || ['','E999'])[1]}</span>
          <span class="pp-error-msg">${node.data._error.replace(/^\[[A-Z]\d+\]\s*/, '')}</span>
        </div>` : ''}
        <div class="pp-body">${renderParamsBody(node)}</div>
      `;
      // 绑定拖动整个面板（点击顶部标题栏）
      const header = paramsPanelEl.querySelector('.pp-header');
      if (header) {
        header.addEventListener('mousedown', panelDragStart);
      }
    }

    // 面板拖动
    function panelDragStart(e) {
      if (e.target.closest('button')) return;   // 点按钮不触发拖动
      if (!paramsPanelEl) return;
      e.stopPropagation();
      const startX = e.clientX, startY = e.clientY;
      const rect = paramsPanelEl.getBoundingClientRect();
      // 用当前 style.left/top 计算基准
      const baseLeft = parseFloat(paramsPanelEl.style.left) || 0;
      const baseTop = parseFloat(paramsPanelEl.style.top) || 0;
      function mv(ev) {
        paramsPanelEl.style.left = (baseLeft + (ev.clientX - startX)) + 'px';
        paramsPanelEl.style.top  = (baseTop  + (ev.clientY - startY)) + 'px';
      }
      function up() {
        document.removeEventListener('mousemove', mv);
        document.removeEventListener('mouseup', up);
      }
      document.addEventListener('mousemove', mv);
      document.addEventListener('mouseup', up);
    }

    // 按节点类型渲染参数字段
    function renderParamsBody(node) {
      const d = node.data;
      if (node.type === 'image_input') return ppImageInputBody(node);
      if (node.type === 'gpt_image') return ppGptImageBody(node);
      if (node.type === 'remove_bg') return ppRemoveBgBody(node);
      if (node.type === 'mask_edit') return ppMaskEditBody(node);
      if (node.type === 'seedance_video') return ppSeedanceBody(node);
      return `<div class="pp-field span-3"><span class="pp-hint">该节点暂无可配置参数</span></div>`;
    }

    // ── image_input ──
    function ppImageInputBody(node) {
      const d = node.data;
      const nid = node.id;
      return `
        <div class="pp-field span-3">
          <div class="pp-label">图片</div>
          <div class="pp-refs">
            <div class="pp-ref-slot ${d.image_url ? 'filled' : ''}"
                 onclick="${d.image_url ? `openLightbox('${d.image_url}')` : `document.getElementById('pp-upload-${nid}').click()`}">
              <div class="pp-ref-label">图片</div>
              ${d.image_url
                ? `<img src="${d.image_url}"/><button class="pp-ref-clear" onclick="event.stopPropagation();clearNodeField('${nid}','image_url')">✕</button>`
                : `<div class="pp-ref-empty">＋ 上传图片</div>`}
            </div>
          </div>
          <input id="pp-upload-${nid}" type="file" accept="image/*" style="display:none"
                 onchange="uploadImage('${nid}',this)"/>
          <div class="pp-hint">上传的图片会作为下游节点的输入</div>
        </div>`;
    }

    // ── remove_bg ──
    function ppRemoveBgBody(_node) {
      return `<div class="pp-field span-3"><span class="pp-hint">此节点无需配置参数。连线上游后点击运行即可去除背景。</span></div>`;
    }

    // ── mask_edit ──
    function ppMaskEditBody(node) {
      const nid = node.id;
      const d = node.data;
      const mode = d.mask_mode || 'auto_face';
      const expand = d.expand ?? 0.25;
      const faceIndex = d.face_index ?? -1;
      const detectMethod = d.detect_method || 'auto';
      const up = getUpstreamByPort(nid, 'image');
      const baseUrl = d.image_url || (up && ((nodeRuntime[up.node.id]?.image_url) || up.node.data.image_url)) || '';
      const upHint = up ? `底图来自上游 ${NODE_CFG[up.node.type]?.title || up.node.type}` : (baseUrl ? '底图来自手动上传' : '请先连线上游图片节点');
      const modeHint = {
        auto_face: '自动检测人脸并生成遮罩（默认）',
        auto_full: '生成全图保留遮罩（不遮脸）',
        manual: '手动绘制遮罩，双击节点打开编辑器'
      }[mode];
      const faceIndexOptions = [
        { value: -1, label: '全部人脸' },
        { value: 0, label: '最大人脸（0）' },
        { value: 1, label: '第二人脸（1）' },
        { value: 2, label: '第三人脸（2）' },
      ].map(o => `<option value="${o.value}" ${faceIndex==o.value?'selected':''}>${o.label}</option>`).join('');
      return `
        <div class="pp-field span-2">
          <div class="pp-label">遮罩模式</div>
          <select onchange="updateNodeData('${nid}','mask_mode',this.value); renderParamsPanel()">
            <option value="auto_face" ${mode==='auto_face'?'selected':''}>自动人脸遮罩</option>
            <option value="auto_full" ${mode==='auto_full'?'selected':''}>自动全图遮罩</option>
            <option value="manual" ${mode==='manual'?'selected':''}>手动绘制</option>
          </select>
          <div class="pp-hint">${modeHint}</div>
          ${mode === 'manual' ? `<button class="pp-btn primary" style="width:fit-content;margin-top:8px" onclick="openMaskEditor('${nid}')">
            ${d.mask_url ? '✎ 重新绘制遮罩' : '＋ 开始绘制遮罩'}
          </button>` : ''}
          <div class="pp-hint" style="margin-top:6px">${upHint}</div>
        </div>
        ${mode === 'auto_face' ? `
        <div class="pp-field">
          <div class="pp-label">检测模型</div>
          <select onchange="updateNodeData('${nid}','detect_method',this.value)">
            <option value="auto" ${detectMethod==='auto'?'selected':''}>自动级联（推荐）</option>
            <option value="opencv_yunet" ${detectMethod==='opencv_yunet'?'selected':''}>YuNet（真实照片）</option>
            <option value="opencv_haar" ${detectMethod==='opencv_haar'?'selected':''}>Haar（无需模型）</option>
          </select>
          <div class="pp-hint">自动级联优先用 YuNet，失败再用 Haar</div>
        </div>
        <div class="pp-field">
          <div class="pp-label">扩展系数</div>
          <input type="range" min="0" max="0.8" step="0.05" value="${expand}"
                 onchange="updateNodeData('${nid}','expand',parseFloat(this.value)); this.nextElementSibling.textContent=this.value">
          <div class="pp-hint">当前值：${expand}（越大遮罩覆盖越多）</div>
        </div>
        <div class="pp-field">
          <div class="pp-label">目标人脸</div>
          <select onchange="updateNodeData('${nid}','face_index',parseInt(this.value))">
            ${faceIndexOptions}
          </select>
          <div class="pp-hint">多人脸时选择指定人脸，默认全部</div>
        </div>` : ''}
        <div class="pp-field">
          <div class="pp-label">当前遮罩</div>
          <div class="pp-refs">
            <div class="pp-ref-slot readonly ${d.mask_url ? 'filled' : ''}"
                 ${d.mask_url ? `onclick="openLightbox('${d.mask_url}')"` : ''}>
              <div class="pp-ref-label">mask</div>
              ${d.mask_url ? `<img src="${d.mask_url}"/>` : `<div class="pp-ref-empty">未生成</div>`}
            </div>
          </div>
        </div>`;
    }

    // ── gpt_image ──
    function ppGptImageBody(node) {
      const d = node.data;
      const nid = node.id;
      const model = d.model || 'gpt-image-2';
      const cfg = AI_IMAGE_MODEL_CFG[model] || AI_IMAGE_MODEL_CFG['gpt-image-2'];
      const isGpt2 = model === 'gpt-image-2';
      const prompt = d.prompt || getDefaultImagePrompt();
      const modelOpts = Object.entries(AI_IMAGE_MODEL_CFG).map(([k,v]) =>
        `<option value="${k}" ${k===model?'selected':''}>${v.label}</option>`).join('');
      const sizeOpts = (cfg.sizes || []).map(s =>
        `<option value="${s}" ${s===(d.size||cfg.defaultSize)?'selected':''}>${s}</option>`).join('');
      const arOpts = (cfg.aspectRatios || []).map(a =>
        `<option value="${a}" ${a===(d.aspect_ratio||cfg.defaultAspect)?'selected':''}>${a}</option>`).join('');
      const resOpts = (cfg.resolutions || []).map(r =>
        `<option value="${r}" ${r===(d.resolution||cfg.defaultRes)?'selected':''}>${r}</option>`).join('');
      const mjVerOpts = (cfg.mjVersions || []).map(v =>
        `<option value="${v}" ${v===(d.mj_version||cfg.defaultMjVersion)?'selected':''}>${v}</option>`).join('');

      // 上游图1（image1 端口，只读）
      const up1 = getUpstreamByPort(nid, 'image1');
      let img1Url = '';
      if (up1) {
        img1Url = (nodeRuntime[up1.node.id]?.image_url) || up1.node.data.image_url || '';
      }
      if (!img1Url) img1Url = d.image1 || d.image_url || '';

      // 上游图2（image2 端口，只读）
      const up2 = getUpstreamByPort(nid, 'image2');
      let img2Url = '';
      if (up2) {
        img2Url = (nodeRuntime[up2.node.id]?.image_url) || up2.node.data.image_url || '';
      }
      if (!img2Url) img2Url = d.image2 || d.image2_url || '';

      // 参考图槽位列表（根据模型定义）
      const refDefs = (() => {
        if (model === 'gpt-image-2') return [
          { field:'__upstream', label:'图1 · 主体(上游)', readonly:true, url: img1Url },
          { field:'hair_url', label:'图2 · 发型' },
          { field:'clothing_url', label:'图3 · 服装' }
        ];
        if (model === 'rh_gpt_image_i2i') return [
          { field:'__upstream', label:'图1 · 主体(上游)', readonly:true, url: img1Url },
          { field:'image2_url', label:'图2 · 参考图', readonly:true, url: img2Url },
          { field:'image2', label:'图2 · 手动参考' }
        ];
        if (model === 'rh_gpt_image_official') return [
          { field:'__upstream', label:'图1 · 主体(上游)', readonly:true, url: img1Url },
          { field:'image2', label:'图2 · 参考图' },
          { field:'hair_url', label:'图3 · 发型' },
          { field:'clothing_url', label:'图4 · 服装' }
        ];
        if (model === 'nano_banana_2') return [
          { field:'__upstream', label:'图1 · 主体(上游)', readonly:true, url: img1Url },
          { field:'image2_url', label:'图2(上游)', readonly:true, url: img2Url },
          { field:'image2', label:'图2 · 手动' },
          { field:'image3_url', label:'图3 · 手动' },
          { field:'image4_url', label:'图4 · 手动' }
        ];
        if (model === 'flux_klein_9b') return [
          { field:'__upstream', label:'图1 · 主体(上游)', readonly:true, url: img1Url }
        ];
        if (model === 'seedream_v4' || model === 'seedream_v5_lite') return [
          { field:'__upstream', label:'图1 · 主体(上游)', readonly:true, url: img1Url },
          { field:'image2', label:'图2 · 参考图' },
          { field:'image3_url', label:'图3 · 参考图' },
          { field:'image4_url', label:'图4 · 参考图' },
          { field:'hair_url', label:'图5 · 发型' },
          { field:'clothing_url', label:'图6 · 服装' }
        ];
        if (model === 'midjourney_v7' || model === 'krea2') return [];
        return [{ field:'__upstream', label:'图1 · 上游', readonly:true, url: img1Url }];
      })();

      const refsHtml = refDefs.map(r => {
        const url = r.readonly ? r.url : d[r.field];
        const filled = !!url;
        if (r.readonly) {
          return `<div class="pp-ref-slot readonly ${filled?'filled':''}"
                       ${url ? `onclick="openLightbox('${url}')"` : ''}>
            <div class="pp-ref-label">${r.label}</div>
            ${url ? `<img src="${url}"/>` : `<div class="pp-ref-empty">来自上游</div>`}
          </div>`;
        }
        return `<div class="pp-ref-slot ${filled?'filled':''}"
                     onclick="${filled ? `openLightbox('${url}')` : `document.getElementById('pp-up-${r.field}-${nid}').click()`}">
          <div class="pp-ref-label">${r.label}</div>
          ${filled
            ? `<img src="${url}"/><button class="pp-ref-clear" onclick="event.stopPropagation();clearNodeField('${nid}','${r.field}')">✕</button>`
            : `<div class="pp-ref-empty">＋ 上传</div>`}
          <input id="pp-up-${r.field}-${nid}" type="file" accept="image/*" style="display:none"
                 onchange="uploadRefImage('${nid}','${r.field}',this)"/>
        </div>`;
      }).join('');

      const sizeField = isGpt2
        ? `<div class="pp-field">
             <div class="pp-label">尺寸 (size)</div>
             <select onchange="updateNodeData('${nid}','size',this.value)">${sizeOpts}</select>
           </div>`
        : `${cfg.aspectRatios ? `<div class="pp-field">
             <div class="pp-label">比例 (aspect ratio)</div>
             <select onchange="updateNodeData('${nid}','aspect_ratio',this.value)">${arOpts}</select>
           </div>` : ''}
           ${cfg.resolutions ? `<div class="pp-field">
             <div class="pp-label">分辨率 (resolution)</div>
             <select onchange="updateNodeData('${nid}','resolution',this.value)">${resOpts}</select>
           </div>` : ''}`;

      const mjVersionField = cfg.mjVersions
        ? `<div class="pp-field">
             <div class="pp-label">MJ 版本</div>
             <select onchange="updateNodeData('${nid}','mj_version',this.value)">${mjVerOpts}</select>
           </div>`
        : '';

      return `
        <div class="pp-field span-2">
          <div class="pp-label">提示词 · Prompt</div>
          <textarea placeholder="输入提示词..." oninput="updateNodeData('${nid}','prompt',this.value)">${prompt}</textarea>
          <div class="pp-hint">${cfg.cost || ''}</div>
        </div>
        <div class="pp-field">
          <div class="pp-label">模型</div>
          <select onchange="setNodeModelFromPanel('${nid}',this.value)">${modelOpts}</select>
        </div>
        ${sizeField}
        ${mjVersionField}
        <div class="pp-field span-3">
          <div class="pp-label">参考图</div>
          <div class="pp-refs">${refsHtml}</div>
        </div>
        <div class="pp-field span-3" style="flex-direction:row;gap:8px;">
          <button class="pp-btn" onclick="polishPrompt('${nid}')">✨ 润色</button>
        </div>`;
    }

    // ── seedance_video ──
    function ppSeedanceBody(node) {
      const d = node.data;
      const nid = node.id;
      const channel = d.channel || 'official';
      const isFirstLast = channel === 'first_last_frame';
      const isSpark = channel === 'seedance_2.0' || channel === 'seedance_2.0_fast';
      const isFast = channel === 'seedance_2.0_fast';
      const isMini = channel === 'seedance_2.0_mini';
      const isSparkLike = isSpark || isMini;  // channels with spark-style options
      const prompt = d.prompt || getDefaultVideoPrompt();

      // 首帧端口 first_frame：优先上游，其次手动值
      const upFirst = getUpstreamByPort(nid, 'first_frame');
      let firstFrameUrl = d.first_frame || d.image_url || '';
      let firstFromUpstream = false;
      if (upFirst) {
        const upUrl = (nodeRuntime[upFirst.node.id]?.image_url) || upFirst.node.data.image_url;
        if (upUrl) { firstFrameUrl = upUrl; firstFromUpstream = true; }
      }

      // 尾帧端口 last_frame：首尾帧/mini 模式有效
      const upLast = (isFirstLast || isMini) ? getUpstreamByPort(nid, 'last_frame') : null;
      let lastFrameUrl = d.last_frame || d.image2_url || '';
      let lastFromUpstream = false;
      if (upLast) {
        const upUrl = (nodeRuntime[upLast.node.id]?.image_url) || upLast.node.data.image_url;
        if (upUrl) { lastFrameUrl = upUrl; lastFromUpstream = true; }
      }

      const ar = d.aspect_ratio || (isSparkLike ? 'adaptive' : '9:16');
      const dur = d.duration || '5';
      const res = d.resolution || (isSparkLike ? '720p' : '480p');

      const arList = isSparkLike
        ? ['adaptive','16:9','4:3','1:1','3:4','9:16','21:9']
        : ['9:16','16:9','1:1','3:4','4:3','21:9'];
      const arOpts = arList.map(a =>
        `<option value="${a}" ${a===ar?'selected':''}>${a}</option>`).join('');
      const durList = isSparkLike
        ? ['-1','4','5','6','7','8','9','10','11','12','13','14','15']
        : ['4','5','6','7','8','9','10','11','12','13','14','15'];
      const durOpts = durList.map(x =>
        `<option value="${x}" ${x===dur?'selected':''}>${x==='-1'?'自动':x+' 秒'}</option>`).join('');
      const resList = (channel === 'seedance_2.0')
        ? ['480p','720p','native1080p','native4k','1080p','2k','4k']
        : ['480p','720p','1080p','2k','4k'];
      const resOpts = resList.map(r =>
        `<option value="${r}" ${r===res?'selected':''}>${r}</option>`).join('');

      // 首帧槽位
      const firstEditable = isFirstLast || isSpark || isMini;
      const firstReadonly = !firstEditable || firstFromUpstream;
      const firstLabelRaw = isSpark ? '参考图' : '首帧';
      const firstLabel = firstFromUpstream ? `图1 · ${firstLabelRaw}（来自 ${NODE_CFG[upFirst.node.type]?.title || upFirst.node.type}）` : `图1 · ${firstLabelRaw}`;
      const firstEmptyReadonly = firstFromUpstream ? '' : (isSpark ? '可选' : '请连线上游');
      const firstEmptyUpload = isSpark ? '＋ 上传参考图' : '＋ 上传首帧';
      const firstSlot = firstReadonly
        ? `<div class="pp-ref-slot readonly ${firstFrameUrl?'filled':''}"
               ${firstFrameUrl ? `onclick="openLightbox('${firstFrameUrl}')"` : ''}>
             <div class="pp-ref-label">${firstLabel}</div>
             ${firstFrameUrl ? `<img src="${firstFrameUrl}"/>` : `<div class="pp-ref-empty">${firstEmptyReadonly}</div>`}
           </div>`
        : `<div class="pp-ref-slot ${firstFrameUrl?'filled':''}"
               onclick="${firstFrameUrl ? `openLightbox('${firstFrameUrl}')` : `document.getElementById('pp-first-${nid}').click()`}">
             <div class="pp-ref-label">${firstLabel}</div>
             ${firstFrameUrl
               ? `<img src="${firstFrameUrl}"/><button class="pp-ref-clear" onclick="event.stopPropagation();clearNodeField('${nid}','first_frame')">✕</button>`
               : `<div class="pp-ref-empty">${firstEmptyUpload}</div>`}
             <input id="pp-first-${nid}" type="file" accept="image/*" style="display:none"
                    onchange="uploadRefImage('${nid}','first_frame',this)"/>
           </div>`;

      // 尾帧槽位（首尾帧/mini 模式可编辑）
      const lastSlot = (isFirstLast || isMini)
        ? (lastFromUpstream
            ? `<div class="pp-ref-slot readonly ${lastFrameUrl?'filled':''}"
                   ${lastFrameUrl ? `onclick="openLightbox('${lastFrameUrl}')"` : ''}>
                 <div class="pp-ref-label">图2 · 尾帧（来自 ${NODE_CFG[upLast.node.type]?.title || upLast.node.type}）</div>
                 ${lastFrameUrl ? `<img src="${lastFrameUrl}"/>` : `<div class="pp-ref-empty"></div>`}
               </div>`
            : `<div class="pp-ref-slot ${lastFrameUrl?'filled':''}"
                   onclick="${lastFrameUrl ? `openLightbox('${lastFrameUrl}')` : `document.getElementById('pp-last-${nid}').click()`}">
                 <div class="pp-ref-label">图2 · 尾帧（可选）</div>
                 ${lastFrameUrl
                   ? `<img src="${lastFrameUrl}"/><button class="pp-ref-clear" onclick="event.stopPropagation();clearNodeField('${nid}','last_frame')">✕</button>`
                   : `<div class="pp-ref-empty">＋ 上传尾帧</div>`}
                 <input id="pp-last-${nid}" type="file" accept="image/*" style="display:none"
                        onchange="uploadRefImage('${nid}','last_frame',this)"/>
               </div>`)
        : isSpark ? '' : `<div class="pp-ref-slot readonly">
             <div class="pp-ref-label">图2</div>
             <div class="pp-ref-empty">普通模式下忽略</div>
           </div>`;

      // 参考视频槽位（仅 spark 模式）
      const videoUrl = d.video_url || '';
      const videoSlot = isSpark
        ? (videoUrl
            ? `<div class="pp-ref-slot filled" onclick="openLightbox('${videoUrl}')">
                 <div class="pp-ref-label">参考视频</div>
                 <video src="${videoUrl}" muted></video>
                 <button class="pp-ref-clear" onclick="event.stopPropagation();clearNodeField('${nid}','video_url')">✕</button>
               </div>`
            : `<div class="pp-ref-slot" onclick="document.getElementById('pp-video-${nid}').click()">
                 <div class="pp-ref-label">参考视频（可选）</div>
                 <div class="pp-ref-empty">＋ 上传视频</div>
                 <input id="pp-video-${nid}" type="file" accept="video/*" style="display:none"
                        onchange="uploadRefImage('${nid}','video_url',this)"/>
               </div>`)
        : '';

      // spark 模式开关
      const genAudio = d.generate_audio === true;
      const realPerson = d.real_person_mode === true;
      const sparkToggles = isSparkLike
        ? `<div class="pp-field span-3" style="flex-direction:row;gap:24px;align-items:center;">
             <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
               <input type="checkbox" ${genAudio?'checked':''}
                      onchange="updateNodeData('${nid}','generate_audio',this.checked)"/>
               <span>生成音频</span>
             </label>
             <label style="display:flex;align-items:center;gap:6px;cursor:pointer;">
               <input type="checkbox" ${realPerson?'checked':''}
                      onchange="updateNodeData('${nid}','real_person_mode',this.checked)"/>
               <span>真人模式</span>
             </label>
           </div>`
        : '';

      return `
        <div class="pp-field span-2">
          <div class="pp-label">提示词 · Video Prompt</div>
          <textarea placeholder="描述视频内容..." oninput="updateNodeData('${nid}','prompt',this.value)">${prompt}</textarea>
          <div class="pp-hint">支持镜头、动作、光线、字幕等描述</div>
        </div>
        <div class="pp-field">
          <div class="pp-label">渠道 (channel)</div>
          <select onchange="updateNodeData('${nid}','channel',this.value); renderParamsPanel()">
            <option value="official" ${channel==='official'?'selected':''}>seedance 官方稳定版</option>
            <option value="low_cost" ${channel==='low_cost'?'selected':''}>seedance 低价版</option>
            <option value="first_last_frame" ${isFirstLast?'selected':''}>seedance 首尾帧</option>
            <option value="seedance_2.0" ${channel==='seedance_2.0'?'selected':''}>seedance 2.0 多模态</option>
            <option value="seedance_2.0_fast" ${channel==='seedance_2.0_fast'?'selected':''}>seedance 2.0 Fast</option>
            <option value="seedance_2.0_mini" ${isMini?'selected':''}>seedance 2.0 Mini 图生视频</option>
          </select>
        </div>
        <div class="pp-field">
          <div class="pp-label">比例</div>
          <select onchange="updateNodeData('${nid}','aspect_ratio',this.value)">${arOpts}</select>
        </div>
        <div class="pp-field">
          <div class="pp-label">时长</div>
          <select onchange="updateNodeData('${nid}','duration',this.value)">${durOpts}</select>
        </div>
        ${isFirstLast || isSparkLike ? `
        <div class="pp-field">
          <div class="pp-label">分辨率</div>
          <select onchange="updateNodeData('${nid}','resolution',this.value)">${resOpts}</select>
        </div>` : ''}
        ${isSpark ? `
        <div class="pp-field span-3">
          <div class="pp-label">参考素材</div>
          <div class="pp-refs" style="grid-template-columns:repeat(2,minmax(140px,1fr));max-width:400px;">
            ${firstSlot}${videoSlot}
          </div>
          <div class="pp-hint">图1为参考图（可选），视频为参考视频（可选，用于视频编辑/续写）</div>
        </div>` : `
        <div class="pp-field span-3">
          <div class="pp-label">首尾帧</div>
          <div class="pp-refs" style="grid-template-columns:repeat(2,minmax(140px,1fr));max-width:400px;">
            ${firstSlot}${lastSlot}
          </div>
          <div class="pp-hint">${isFirstLast ? '首尾帧模式：图1必填，图2可选（尾帧）' : isMini ? 'Mini 模式：图1必填（首帧），图2可选（尾帧）' : '普通模式：图1来自上游连线，图2被忽略'}</div>
        </div>`}
        ${sparkToggles}`;
    }

    // 从参数面板切换模型（需要走 setNodeModel 保证参数迁移）
    function setNodeModelFromPanel(nodeId, model) {
      setNodeModel(nodeId, model);
      renderParamsPanel();
    }
    window.setNodeModelFromPanel = setNodeModelFromPanel;

    // 从参数面板直接运行节点
    function runNodeFromPanel(nodeId) {
      selectedNode = nodeId;
      document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
      const el = nodeElements[nodeId];
      if (el) el.classList.add('selected');
      updateRunSelectedBtn();
      if (typeof runSelected === 'function') runSelected();
    }
    window.runNodeFromPanel = runNodeFromPanel;

    // ESC 关闭面板
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && paramsPanelNodeId) {
        // 但不打断遮罩编辑器等
        if (document.getElementById('mask-editor')?.classList.contains('open')) return;
        closeParamsPanel();
      }
    });

    // 点击画布空白：关闭参数面板 + 清除选中
    document.addEventListener('mousedown', (e) => {
      // 只在 viewport 空白处触发
      if (e.target.id !== 'viewport' && e.target.id !== 'workspace') return;
      // 不要影响框选/平移
      if (e.button !== 0) return;
      if (paramsPanelNodeId) closeParamsPanel();
    });

    // ─── 框选多选辅助 ───
    function toggleNodeBoxSelection(id) {
      if (selectedNodes.has(id)) {
        selectedNodes.delete(id);
        nodeElements[id]?.classList.remove('box-selected');
      } else {
        selectedNodes.add(id);
        nodeElements[id]?.classList.add('box-selected');
      }
      // 多选与单选互斥
      selectedNode = null;
      document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
      updateRunSelectedBtn();
    }

    function clearBoxSelection() {
      if (selectedNodes.size === 0) return;
      selectedNodes.clear();
      document.querySelectorAll('.node.box-selected').forEach(n => n.classList.remove('box-selected'));
      updateRunSelectedBtn();
    }

    function updateRunSelectedBtn() {
      const btn = document.getElementById('btn-run-selected');
      if (!btn) return;
      const n = selectedNodes.size;
      if (n > 0) {
        btn.textContent = `运行选中 (${n})`;
        btn.disabled = false;
      } else if (selectedNode) {
        btn.textContent = '运行选中 (1)';
        btn.disabled = false;
      } else {
        btn.textContent = '运行选中 (0)';
        btn.disabled = true;
      }
    }

    function runSelected() {
      let nodeIds;
      if (selectedNodes.size > 0) {
        nodeIds = [...selectedNodes];
      } else if (selectedNode) {
        nodeIds = [selectedNode];
      } else {
        showToast('请先选择节点（单击选中运行链路，或 Shift+框选运行部分）');
        return;
      }
      // 严格检查前置依赖：必须所有直接上游都成功完成才能运行
      const blocking = findBlockingUpstreams(nodeIds);
      if (blocking.length > 0) {
        const names = blocking.map(b => `${b.title}(${b.id.slice(0,6)})`).join('、');
        showToast(`以下上游节点尚未完成，请先运行它们：\n${names}\n\n补齐后再点击「运行选中」。`);
        return;
      }
      runCanvas(nodeIds);
    }

    // ═══════════════════════════════════════════════════════════════
    // 画布交互
    // ═══════════════════════════════════════════════════════════════
    const viewport = document.getElementById('viewport');
    viewport.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = viewport.getBoundingClientRect();
      const mx = e.clientX-r.left, my = e.clientY-r.top;
      const wx = (mx-viewX)/viewScale, wy = (my-viewY)/viewScale;
      const f = e.deltaY < 0 ? 1.1 : 0.9;
      viewScale = Math.max(0.2, Math.min(3, viewScale*f));
      viewX = mx-wx*viewScale; viewY = my-wy*viewScale;
      applyTransform();
    }, { passive: false });

    document.addEventListener('dblclick', (e) => {
      if (e.target.closest('.node') || e.target.closest('#side-panel') || e.target.closest('#toolbar')) return;
      openSidePanel();
    });

    let spaceDown = false;
    document.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && !spaceDown && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
        spaceDown = true; viewport.style.cursor = 'grab';
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        e.preventDefault();
        if (e.shiftKey) redo(); else undo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || e.key === 'Y')) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        e.preventDefault();
        redo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C') && !e.shiftKey) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        e.preventDefault();
        // 复制：优先框选节点，否则单选节点所在链路
        let srcNodes;
        if (selectedNodes.size > 0) {
          srcNodes = canvasData.nodes.filter(n => selectedNodes.has(n.id));
        } else if (selectedNode) {
          const chainIds = getChainNodeIds(selectedNode);
          srcNodes = canvasData.nodes.filter(n => chainIds.has(n.id));
        } else {
          return;
        }
        const idSet = new Set(srcNodes.map(n => n.id));
        const srcConns = canvasData.connections.filter(c => idSet.has(c.from) && idSet.has(c.to));
        clipboardGraph = { nodes: JSON.parse(JSON.stringify(srcNodes)), connections: JSON.parse(JSON.stringify(srcConns)) };
        return;
      }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'v' || e.key === 'V') && !e.shiftKey) {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        e.preventDefault();
        if (!clipboardGraph || clipboardGraph.nodes.length === 0) return;
        pushHistory();
        const idMap = {};
        const offsetX = 40, offsetY = 40;
        // 先清除运行态数据，生成新 id
        for (const old of clipboardGraph.nodes) {
          const newId = uid();
          idMap[old.id] = newId;
          const newNode = {
            id: newId,
            type: old.type,
            x: old.x + offsetX,
            y: old.y + offsetY,
            data: JSON.parse(JSON.stringify(old.data))
          };
          delete newNode.data._error;
          delete newNode.data._width;
          delete newNode.data._height;
          canvasData.nodes.push(newNode);
          renderNode(newNode);
        }
        // 复制内部连线
        for (const c of clipboardGraph.connections) {
          if (idMap[c.from] && idMap[c.to]) {
            canvasData.connections.push({ id: uid(), from: idMap[c.from], to: idMap[c.to], fromField: c.fromField, toField: c.toField });
          }
        }
        // 选中新复制的节点
        clearBoxSelection();
        if (selectedNode) { selectedNode = null; document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected')); }
        for (const old of clipboardGraph.nodes) {
          const newId = idMap[old.id];
          selectedNodes.add(newId);
          nodeElements[newId]?.classList.add('box-selected');
        }
        updateRunSelectedBtn();
        renderConnections();
        updateStatusbar();
        autoSave();
        return;
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (selectedConn) {
          pushHistory();
          canvasData.connections = canvasData.connections.filter(c=>c.id!==selectedConn);
          selectedConn = null; renderConnections(); updateStatusbar(); autoSave();
        } else if (selectedNodes.size > 0) {
          pushHistory();
          [...selectedNodes].forEach(removeNode);
          clearBoxSelection();
        } else if (selectedNode) { removeNode(selectedNode); }
      }
      if (e.key === 'Escape') {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        clearBoxSelection();
        selectedNode = null; selectedConn = null;
        document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
        updateRunSelectedBtn();
        renderConnections();
      }
    });
    document.addEventListener('keyup', (e) => {
      if (e.code === 'Space') { spaceDown = false; viewport.style.cursor = 'default'; }
    });

    viewport.addEventListener('mousedown', (e) => {
      const mid = e.button === 1, sp = e.button === 0 && spaceDown;
      const onNode = e.target.closest('.node');
      const leftBlank = e.button === 0 && !onNode;
      // 连线模式优先：左键在 port-in 上完成连线，在空白处取消
      if (isConnecting && e.button === 0) {
        const t = document.elementFromPoint(e.clientX, e.clientY);
        if (t && t.classList.contains('port-in')) {
          const tn = t.closest('.node');
          if (tn && tn.dataset.id !== connStart) {
            const id = tn.dataset.id;
            if (!canvasData.connections.some(c=>c.from===connStart&&c.to===id)) {
              pushHistory();
              canvasData.connections.push({ id: uid(), from: connStart, to: id });
              renderConnections(); updateStatusbar(); autoSave();
            }
          }
        }
        isConnecting = false; connStart = null;
        const temp = document.getElementById('svg-layer').querySelector('.conn-temp');
        if (temp) temp.remove();
        return;
      }
      if (!mid && !sp && !leftBlank) return;
      // Shift + 左键空白 = 框选模式（优先于平移）
      if (e.shiftKey && leftBlank) {
        e.preventDefault();
        isBoxSelecting = true;
        boxSelectMoved = false;
        const r = viewport.getBoundingClientRect();
        boxStart = screenToCanvas(e.clientX - r.left, e.clientY - r.top);
        boxEnd = { x: boxStart.x, y: boxStart.y };
        viewport.classList.add('box-selecting');
        return;
      }
      e.preventDefault();
      isPanning = true; viewport.classList.add('panning');
      panStart = { x: e.clientX, y: e.clientY, vx: viewX, vy: viewY };
    });

    document.addEventListener('mousemove', (e) => {
      if (isBoxSelecting) {
        const r = viewport.getBoundingClientRect();
        boxEnd = screenToCanvas(e.clientX - r.left, e.clientY - r.top);
        if (Math.abs(boxEnd.x - boxStart.x) > 3 || Math.abs(boxEnd.y - boxStart.y) > 3) {
          boxSelectMoved = true;
        }
        let rect = document.getElementById('svg-layer').querySelector('.box-select-rect');
        if (!rect) {
          rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          rect.setAttribute('class', 'box-select-rect');
          document.getElementById('svg-layer').appendChild(rect);
        }
        const x = Math.min(boxStart.x, boxEnd.x), y = Math.min(boxStart.y, boxEnd.y);
        const w = Math.abs(boxEnd.x - boxStart.x), h = Math.abs(boxEnd.y - boxStart.y);
        rect.setAttribute('x', x); rect.setAttribute('y', y);
        rect.setAttribute('width', w); rect.setAttribute('height', h);
        return;
      }
      if (isPanning) {
        viewX = panStart.vx + (e.clientX-panStart.x);
        viewY = panStart.vy + (e.clientY-panStart.y);
        applyTransform(); return;
      }
      if (isConnecting && connStart) {
        const fn = canvasData.nodes.find(n=>n.id===connStart.nodeId);
        const fe = nodeElements[connStart.nodeId];
        if (!fn || !fe) return;
        const startPort = fe.querySelector(`.port-out[data-portname="${connStart.portName}"]`);
        const startPos = getPortCenter(fn, fe, startPort, 'out');
        const r = viewport.getBoundingClientRect();
        const c = screenToCanvas(e.clientX-r.left, e.clientY-r.top);
        const dx = Math.max(40, Math.abs(c.x-startPos.x)*0.35);
        const p = `M ${startPos.x} ${startPos.y} C ${startPos.x+dx} ${startPos.y}, ${c.x-dx} ${c.y}, ${c.x} ${c.y}`;
        let t = document.getElementById('svg-layer').querySelector('.conn-temp');
        if (!t) { t = document.createElementNS('http://www.w3.org/2000/svg','path'); t.setAttribute('class','conn-temp'); document.getElementById('svg-layer').appendChild(t); }
        t.setAttribute('d', p);
      }
    });
    // 计算端口在 canvas 坐标系中的中心点
    function getPortCenter(node, el, portEl, dir) {
      if (!portEl) {
        // 无指定端口：取左侧/右侧中点
        return dir === 'out'
          ? { x: node.x + el.offsetWidth, y: node.y + el.offsetHeight / 2 }
          : { x: node.x, y: node.y + el.offsetHeight / 2 };
      }
      const portIndex = parseInt(portEl.style.getPropertyValue('--port-index') || '0', 10);
      const portCount = parseInt(portEl.style.getPropertyValue('--port-count') || '1', 10);
      const topPct = 0.18 + portIndex * (0.64 / Math.max(portCount - 1, 1));
      const y = node.y + el.offsetHeight * topPct;
      return dir === 'out'
        ? { x: node.x + el.offsetWidth, y }
        : { x: node.x, y };
    }

    document.addEventListener('mouseup', (e) => {
      if (isConnecting && connStart) {
        const t = document.elementFromPoint(e.clientX, e.clientY);
        if (t && t.classList.contains('port-in')) {
          const tn = t.closest('.node');
          if (tn && tn.dataset.id !== connStart.nodeId) {
            const id = tn.dataset.id;
            const toField = t.dataset.portname;
            const fromField = connStart.portName;
            if (!canvasData.connections.some(c=>c.from===connStart.nodeId&&c.to===id&&c.toField===toField)) {
              pushHistory();
              canvasData.connections.push({
                id: uid(),
                from: connStart.nodeId,
                fromField,
                to: id,
                toField
              });
              renderConnections(); updateStatusbar(); autoSave();
            }
          }
        }
        isConnecting = false; connStart = null;
        const temp = document.getElementById('svg-layer').querySelector('.conn-temp');
        if (temp) temp.remove();
      }
      if (isPanning) { isPanning = false; viewport.classList.remove('panning'); }
      if (!isBoxSelecting) return;
      isBoxSelecting = false;
      viewport.classList.remove('box-selecting');
      const rect = document.getElementById('svg-layer').querySelector('.box-select-rect');
      if (rect) rect.remove();
      // 未拖动（Shift+点空白）= 清空多选
      if (!boxSelectMoved) {
        clearBoxSelection();
        suppressNextBlankClick = true;
        return;
      }
      // AABB 相交测试（canvas 坐标系，节点 left/top + offsetWidth/Height）
      const bx1 = Math.min(boxStart.x, boxEnd.x), by1 = Math.min(boxStart.y, boxEnd.y);
      const bx2 = Math.max(boxStart.x, boxEnd.x), by2 = Math.max(boxStart.y, boxEnd.y);
      selectedNodes.clear();
      document.querySelectorAll('.node.box-selected').forEach(n => n.classList.remove('box-selected'));
      canvasData.nodes.forEach(n => {
        const el = nodeElements[n.id];
        if (!el) return;
        const nx1 = n.x, ny1 = n.y;
        const nx2 = n.x + el.offsetWidth, ny2 = n.y + el.offsetHeight;
        if (nx1 < bx2 && nx2 > bx1 && ny1 < by2 && ny2 > by1) {
          selectedNodes.add(n.id);
          el.classList.add('box-selected');
        }
      });
      selectedNode = null;
      document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
      updateRunSelectedBtn();
      // 抑制 mouseup 后紧随的 click 事件清空选择
      suppressNextBlankClick = true;
    });

    let ctxPos = { x:0, y:0 };
    viewport.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      const r = viewport.getBoundingClientRect();
      ctxPos = screenToCanvas(e.clientX-r.left, e.clientY-r.top);
      const m = document.getElementById('context-menu');
      m.style.display = 'block'; m.style.left = e.clientX+'px'; m.style.top = e.clientY+'px';
    });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('#context-menu')) hideContextMenu();
      // 框选 mouseup 后抑制一次清空（避免刚框选完就被 click 清掉）
      if (suppressNextBlankClick) { suppressNextBlankClick = false; return; }
      if (!e.target.closest('.node') && !e.target.closest('.conn-path')) {
        selectedNode = null; selectedConn = null;
        clearBoxSelection();
        document.querySelectorAll('.node.selected').forEach(n=>n.classList.remove('selected'));
        updateRunSelectedBtn();
        renderConnections();
      }
    });
    function hideContextMenu() { document.getElementById('context-menu').style.display = 'none'; }

    // ═══════════════════════════════════════════════════════════════
    // 运行画布
    // ═══════════════════════════════════════════════════════════════
    // ═══════════ toast 消息条 ═══════════
    function showToast(msg, type) {
      type = type || 'info';
      var box = document.getElementById('toast-container');
      if (!box) { box = document.createElement('div'); box.id = 'toast-container'; document.body.appendChild(box); }
      var el = document.createElement('div');
      el.className = 'toast ' + type;
      el.textContent = msg;
      box.appendChild(el);
      var ms = type === 'error' ? 5000 : 3000;
      setTimeout(function(){ el.classList.add('fade-out'); setTimeout(function(){ el.remove(); }, 300); }, ms);
    }

    async function runCanvas(nodeIds) {
      // nodeIds 可选：不传=运行全部；传=只运行该子集节点
      // 后端根据 canvas_id 查找上游历史产物，无需前端注入补丁
      let nodes = canvasData.nodes, conns = canvasData.connections;
      let runSet = null;
      if (nodeIds && nodeIds.length) {
        runSet = new Set(nodeIds);
        nodes = canvasData.nodes.filter(n => runSet.has(n.id));
        conns = canvasData.connections.filter(c => runSet.has(c.from) && runSet.has(c.to));
      }
      if (nodes.length === 0) { showToast('没有可运行的节点', 'error'); return; }

      Object.keys(pollTimers).forEach(stopPolling);
      const r = await _apiFetch('/api/canvas/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          canvas_id: activeCanvasId || '',                         // 画布定义 ID
          nodes: nodes.map(n => ({ id:n.id, type:n.type, x:n.x, y:n.y, data:n.data })),
          connections: conns.map(c => ({
            id: c.id,
            from: c.from,
            fromField: c.fromField,
            to: c.to,
            toField: c.toField,
          })),
          run_node_ids: nodes.map(n => n.id),                      // 本次运行的节点
          approval_mode: approvalMode,                              // 批准模式开关
        })
      });
      if (!r.ok) { showToast('提交失败: HTTP ' + r.status, 'error'); return; }
      const d = await r.json();
      currentCanvasId = d.canvas_id;
      nodeRuntime = {};
      for (const n of nodes) { nodeRuntime[n.id] = { status:'pending', progress:0 }; startPolling(n.id); }
      updateStatusbar('running');
      showToast('已提交 ' + nodes.length + ' 个节点运行', 'info');
    }
    function runChain() {
      if (!selectedNode) { showToast('请先选中要运行的链路中的任意节点'); return; }
      runCanvas([...getChainNodeIds(selectedNode)]);
    }

    function toggleApprovalMode() {
      approvalMode = !approvalMode;
      localStorage.setItem('approval_mode', approvalMode ? 'true' : 'false');
      updateApprovalButton();
    }
    function updateApprovalButton() {
      const btn = document.getElementById('btn-approval');
      if (!btn) return;
      if (approvalMode) {
        btn.classList.add('active');
        btn.textContent = '批准模式：开';
      } else {
        btn.classList.remove('active');
        btn.textContent = '批准模式';
      }
    }
    async function approveNode(nodeId) {
      if (!currentCanvasId) return;
      try {
        const r = await _apiFetch(`/api/canvas/${currentCanvasId}/approve/${nodeId}`, { method: 'POST' });
        if (!r.ok) { const d = await r.json(); showToast(d.detail || '批准失败'); return; }
        startPolling(nodeId); // 级联执行后下游节点会自动进入 pending/running
        updateNodeUI(nodeId, { status: 'success', progress: 100, image_url: nodeRuntime[nodeId]?.image_url, video_url: nodeRuntime[nodeId]?.video_url, mask_url: nodeRuntime[nodeId]?.mask_url });
      } catch(e) { showToast('批准请求失败'); }
    }
    async function rejectNode(nodeId) {
      if (!currentCanvasId) return;
      try {
        const r = await _apiFetch(`/api/canvas/${currentCanvasId}/reject/${nodeId}`, { method: 'POST' });
        if (!r.ok) { const d = await r.json(); showToast(d.detail || '拒绝失败'); return; }
        updateNodeUI(nodeId, { status: 'failed', progress: 100, error: '用户拒绝该生成结果' });
      } catch(e) { showToast('拒绝请求失败'); }
    }
    window.toggleApprovalMode = toggleApprovalMode;
    window.approveNode = approveNode;
    window.rejectNode = rejectNode;

    // ─── 轮询聚合：单定时器批量拉取所有节点状态，替代 N 节点 N 次 GET ───
    let canvasPollTimer = null;
    function startPolling(nodeId) {
      // 兼容旧调用：启动整个画布的批量轮询（nodeId 参数忽略）
      startCanvasPolling();
    }
    function startCanvasPolling() {
      if (canvasPollTimer) return;  // 已在轮询
      canvasPollTimer = setInterval(async () => {
        if (!currentCanvasId) return;
        try {
          const r = await _apiFetch(`/api/canvas/${currentCanvasId}/nodes`);
          if (!r.ok) return;
          const data = await r.json();
          const nodes = data.nodes || [];
          let allDone = nodes.length > 0;
          for (const d of nodes) {
            updateNodeUI(d.node_id, d);
            if (!['success','failed','blocked','interrupted','awaiting_approval'].includes(d.status)) allDone = false;
            if (d.status === 'awaiting_approval') renderApprovalActions(d.node_id);
          }
          if (allDone) { stopCanvasPolling(); checkAllDone(); }
        } catch(e) {}
      }, 800);
    }
    function stopPolling(nodeId) {
      // 兼容旧调用：停整个画布轮询（nodeId 参数忽略）
      stopCanvasPolling();
    }
    function stopCanvasPolling() {
      if (canvasPollTimer) { clearInterval(canvasPollTimer); canvasPollTimer = null; renderConnections(); }
    }
    function updateNodeUI(nodeId, d) {
      const prevStatus = nodeRuntime[nodeId]?.status;
      nodeRuntime[nodeId] = { status: d.status, progress: d.progress, image_url: d.image_url, video_url: d.video_url, mask_url: d.mask_url };
      const badge = document.getElementById('badge-'+nodeId);
      if (badge) { badge.textContent = STATUS_LABELS[d.status]||d.status; badge.className = 'node-badge '+d.status; }
      const prog = document.getElementById('prog-'+nodeId);
      if (prog) { prog.style.width = d.progress+'%'; prog.className = 'fill '+d.status; }
      const node = canvasData.nodes.find(n=>n.id===nodeId);
      if (node) {
        let changed = false;
        if (d.image_url && node.data.image_url !== d.image_url) { node.data.image_url = d.image_url; changed = true; }
        if (d.video_url && node.data.video_url !== d.video_url) { node.data.video_url = d.video_url; changed = true; }
        if (d.mask_url && node.data.mask_url !== d.mask_url) { node.data.mask_url = d.mask_url; changed = true; }
        if (d.width) { node.data._width = d.width; changed = true; }
        if (d.height) { node.data._height = d.height; changed = true; }
        if (changed) refreshNodePreview(nodeId);
      }
      if (d.error) { const node2 = canvasData.nodes.find(n=>n.id===nodeId); if(node2) { node2.data._error = d.error; refreshNodePreview(nodeId); } }
        // 失败时即时 toast + 自动打开参数面板展示错误
        if (d.status === 'failed' && prevStatus !== 'failed') {
          showToast('节点 #' + nodeId.slice(0,6) + ' 失败: ' + (d.error || '未知错误').slice(0, 60), 'error');
          if (!paramsPanelNodeId) openParamsPanel(nodeId);
        }
      // 状态变化时刷新连线颜色
      if (prevStatus !== d.status) renderConnections();
      // 同步状态栏计数
      updateStatusbar(d.status === 'running' ? 'running' : undefined);
      // 参数面板打开的是本节点：刷新头部状态
      if (paramsPanelNodeId === nodeId) {
        const sub = document.querySelector('#node-params-panel .pp-subtitle');
        if (sub) sub.textContent = `#${nodeId.slice(0,6)} · ${STATUS_LABELS[d.status]||d.status}`;
      }
      // 待批准状态渲染通过/拒绝按钮
      if (d.status === 'awaiting_approval') renderApprovalActions(nodeId);
      else removeApprovalActions(nodeId);
    }
    function renderApprovalActions(nodeId) {
      const el = nodeElements[nodeId];
      if (!el) return;
      let layer = el.querySelector('.approval-actions');
      if (!layer) {
        layer = document.createElement('div');
        layer.className = 'approval-actions';
        el.appendChild(layer);
      }
      layer.innerHTML = `
        <div class="approval-title">待批准</div>
        <button class="tb-btn primary" onclick="event.stopPropagation();approveNode('${nodeId}')">通过</button>
        <button class="tb-btn danger" onclick="event.stopPropagation();rejectNode('${nodeId}')">拒绝</button>
      `;
    }
    function removeApprovalActions(nodeId) {
      const el = nodeElements[nodeId];
      if (!el) return;
      const layer = el.querySelector('.approval-actions');
      if (layer) layer.remove();
    }
    function checkAllDone() {
      if (!canvasPollTimer) {
        updateStatusbar('done');
        // 聚合完成 toast
        var succ = 0, fail = 0;
        for (var nid in nodeRuntime) {
          var s = nodeRuntime[nid] && nodeRuntime[nid].status;
          if (s === 'success') succ++;
          else if (s === 'failed' || s === 'blocked' || s === 'interrupted') fail++;
        }
        if (fail > 0) showToast('完成：成功 ' + succ + ' / 失败 ' + fail, fail > succ ? 'error' : 'info');
        else showToast('全部完成（' + succ + ' 个节点）', 'success');
        const outputs = getCompareOutputs();
        if (outputs.length >= 2) showCompare();
      }
    }
    function getCompareOutputs() {
      return canvasData.nodes.filter(n => {
        const rt = nodeRuntime[n.id];
        return rt && rt.status === 'success' && (rt.image_url || rt.video_url);
      });
    }
    function showCompare() {
      const outputs = getCompareOutputs();
      const grid = document.getElementById('compare-grid');
      if (outputs.length === 0) {
        grid.innerHTML = '<div style="color:#555;font-size:12px;grid-column:1/-1;text-align:center;padding:30px">暂无已完成的产出节点</div>';
      } else {
        grid.innerHTML = outputs.map(n => {
          const cfg = NODE_CFG[n.type] || { title: n.type, color: '#555' };
          const rt = nodeRuntime[n.id];
          const url = (rt && rt.video_url) ? rt.video_url : (rt ? rt.image_url : null) || n.data.video_url || n.data.image_url;
          const isVideo = !!(rt && rt.video_url) || !!(n.data && n.data.video_url);
          const media = isVideo ? `<video src="${url}" muted></video>` : `<img src="${url}" />`;
          return `<div class="compare-card" onclick="openLightbox('${url}', ${isVideo})">
            ${media}
            <div class="cc-meta">
              <span class="cc-dot" style="background:${cfg.color}"></span>
              <span class="cc-title">${cfg.title}</span>
              <span class="cc-id">${n.id.slice(0,6)}</span>
            </div>
          </div>`;
        }).join('');
      }
      document.getElementById('compare-modal').classList.add('show');
    }
    function closeCompare() { document.getElementById('compare-modal').classList.remove('show'); }
    function openLightbox(url, isVideo) {
      const m = document.getElementById('lightbox-media');
      m.innerHTML = isVideo ? `<video src="${url}" controls autoplay></video>` : `<img src="${url}" />`;
      document.getElementById('compare-lightbox').classList.add('show');
    }
    function closeLightbox() { document.getElementById('compare-lightbox').classList.remove('show'); }

    // ═══════════════════════════════════════════════════════════════
    // minimap 小地图
    // ═══════════════════════════════════════════════════════════════
    let minimapRaf = null;
    function scheduleMinimap() {
      if (minimapRaf) return;
      minimapRaf = requestAnimationFrame(() => { minimapRaf = null; updateMinimap(); });
    }
    function getMinimapBounds() {
      let minX=Infinity, minY=Infinity, maxX=-Infinity, maxY=-Infinity;
      for (const n of canvasData.nodes) {
        const el = nodeElements[n.id];
        const w = el ? el.offsetWidth : 210, h = el ? el.offsetHeight : 100;
        if (n.x < minX) minX = n.x; if (n.y < minY) minY = n.y;
        if (n.x + w > maxX) maxX = n.x + w; if (n.y + h > maxY) maxY = n.y + h;
      }
      const pad = 40;
      minX -= pad; minY -= pad; maxX += pad; maxY += pad;
      const fit = Math.min(180 / (maxX - minX), 120 / (maxY - minY));
      return { minX, minY, maxX, maxY, fit };
    }
    function updateMinimap() {
      const mc = document.getElementById('minimap-content');
      const mv = document.getElementById('minimap-viewport');
      if (!mc || !mv) return;
      if (canvasData.nodes.length === 0) {
        mc.innerHTML = ''; mv.style.width = '0'; mv.style.height = '0'; return;
      }
      const { minX, minY, fit } = getMinimapBounds();
      let html = '';
      for (const n of canvasData.nodes) {
        const cfg = NODE_CFG[n.type] || { color: '#555' };
        const el = nodeElements[n.id];
        const w = (el ? el.offsetWidth : 210) * fit, h = (el ? el.offsetHeight : 100) * fit;
        const x = (n.x - minX) * fit, y = (n.y - minY) * fit;
        html += `<div class="mm-node" style="left:${x}px;top:${y}px;width:${Math.max(2,w)}px;height:${Math.max(2,h)}px;background:${cfg.color}"></div>`;
      }
      mc.innerHTML = html;
      const vp = document.getElementById('viewport').getBoundingClientRect();
      const cx1 = (0 - viewX) / viewScale, cy1 = (0 - viewY) / viewScale;
      const cx2 = (vp.width - viewX) / viewScale, cy2 = (vp.height - viewY) / viewScale;
      mv.style.left = ((cx1 - minX) * fit) + 'px';
      mv.style.top = ((cy1 - minY) * fit) + 'px';
      mv.style.width = Math.max(4, (cx2 - cx1) * fit) + 'px';
      mv.style.height = Math.max(3, (cy2 - cy1) * fit) + 'px';
    }
    function onMinimapClick(e) {
      if (canvasData.nodes.length === 0) return;
      const r = document.getElementById('minimap').getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      const { minX, minY, fit } = getMinimapBounds();
      const cx = mx / fit + minX, cy = my / fit + minY;
      const vp = document.getElementById('viewport').getBoundingClientRect();
      viewX = vp.width/2 - cx * viewScale;
      viewY = vp.height/2 - cy * viewScale;
      applyTransform();
    }

    // ═══════════════════════════════════════════════════════════════
    // 画布持久化
    // ═══════════════════════════════════════════════════════════════
    let autoSaveTimer = null;
    function autoSave() {
      clearTimeout(autoSaveTimer);
      autoSaveTimer = setTimeout(() => {
        localStorage.setItem('autosave', JSON.stringify(canvasData));
      }, 2000);
    }

    async function saveCanvas() {
      const defaultName = activeCanvasId ? canvasData.name || '我的画布' : '我的画布';
      const name = prompt('项目名称：', defaultName);
      if (!name) return;
      const r = await _apiFetch('/api/canvas/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: activeCanvasId || '',
          name,
          nodes: canvasData.nodes.map(n => ({ id:n.id, type:n.type, x:n.x, y:n.y, data:n.data })),
          connections: canvasData.connections.map(c => ({ id:c.id, from:c.from, to:c.to, fromField:c.fromField, toField:c.toField }))
        })
      });
      const d = await r.json();
      const isUpdate = activeCanvasId === d.id && activeCanvasId;
      activeCanvasId = d.id;
      canvasData.name = d.name;
      refreshProjectDrawer();
      showToast(`已${isUpdate ? '更新' : '保存'}：${d.name}（${d.id}）`);
    }
    async function newProject() {
      if (!confirm('新建项目会清空当前画布，是否继续？')) return;
      pushHistory();
      canvasData.nodes.forEach(n => stopPolling(n.id));
      canvasData = { nodes: [], connections: [] };
      Object.values(nodeElements).forEach(el => el.remove());
      Object.keys(nodeElements).forEach(k => delete nodeElements[k]);
      selectedNode = null; currentCanvasId = null; activeCanvasId = null;
      nodeRuntime = {};
      renderConnections(); updateStatusbar(); updateRunSelectedBtn();
      closeModal();
      // 放入两个示例节点引导
      addNodeAt('image_input', 260, 250);
      addNodeAt('gpt_image', 760, 250);
      renderConnections();
      autoSave();
    }
    async function cloneCanvas(id) {
      try {
        const r = await _apiFetch(`/api/canvas/${id}/clone`, { method: 'POST' });
        if (!r.ok) { showToast('复制失败'); return; }
        const d = await r.json();
        loadCanvasList();
        refreshProjectDrawer();
        showToast(`已复制为新项目：${d.name}（${d.id}）`);
      } catch(e) { showToast('复制失败：' + e.message); }
    }

    // ═══════════════════════════════════════════════════════════════
    // 运营前台：模式切换 + 主播库 + 模板库
    // ═══════════════════════════════════════════════════════════════
    let opsState = {
      streamers: [],
      selectedStreamers: [],
      templates: [],
      selectedTemplateId: null,
      newStreamerImageUrl: null,
      candidateNum: 3,
    };


// ─── 命名空间挂载：把本模块声明式函数挂到 TuanboApp.canvas 做索引 ───
Object.assign(TuanboApp.canvas, {
  uid: uid,
  snapshotCanvas: snapshotCanvas,
  pushHistory: pushHistory,
  restoreSnapshot: restoreSnapshot,
  undo: undo,
  redo: redo,
  updateUndoRedoButtons: updateUndoRedoButtons,
  applyTransform: applyTransform,
  resetView: resetView,
  zoomBy: zoomBy,
  screenToCanvas: screenToCanvas,
  addNode: addNode,
  openSidePanel: openSidePanel,
  closeSidePanel: closeSidePanel,
  addNodeFromPanel: addNodeFromPanel,
  addNodeAt: addNodeAt,
  getDefaultData: getDefaultData,
  removeNode: removeNode,
  clearCanvas: clearCanvas,
  getChainNodeIds: getChainNodeIds,
  getUpstreamNodeIds: getUpstreamNodeIds,
  getUpstreamByPort: getUpstreamByPort,
  findBlockingUpstreams: findBlockingUpstreams,
  cloneChain: cloneChain,
  renderNode: renderNode,
  buildNodeHTML: buildNodeHTML,
  portTypeFor: portTypeFor,
  buildNodePreview: buildNodePreview,
  buildPreviewTools: buildPreviewTools,
  downloadAsset: downloadAsset,
  buildNodeMeta: buildNodeMeta,
  buildNodeBody: buildNodeBody,
  updateNodeData: updateNodeData,
  migrateNodeData: migrateNodeData,
  refreshNodeBody: refreshNodeBody,
  setNodeModel: setNodeModel,
  updateCharCount: updateCharCount,
  getDefaultImagePrompt: getDefaultImagePrompt,
  getDefaultVideoPrompt: getDefaultVideoPrompt,
  polishPrompt: polishPrompt,
  refreshNodePreview: refreshNodePreview,
  uploadImage: uploadImage,
  uploadRefImage: uploadRefImage,
  clearNodeField: clearNodeField,
  openMaskEditor: openMaskEditor,
  compositeMask: compositeMask,
  redrawMask: redrawMask,
  closeMaskEditor: closeMaskEditor,
  toggleEraser: toggleEraser,
  clearMask: clearMask,
  getMaskPos: getMaskPos,
  startMaskDraw: startMaskDraw,
  drawMask: drawMask,
  stopMaskDraw: stopMaskDraw,
  saveMask: saveMask,
  getDefaultPortName: getDefaultPortName,
  renderConnections: renderConnections,
  bindNodeEvents: bindNodeEvents,
  ensureParamsPanel: ensureParamsPanel,
  positionParamsPanel: positionParamsPanel,
  openParamsPanel: openParamsPanel,
  closeParamsPanel: closeParamsPanel,
  togglePpGroup: togglePpGroup,
  renderParamsPanel: renderParamsPanel,
  panelDragStart: panelDragStart,
  renderParamsBody: renderParamsBody,
  ppImageInputBody: ppImageInputBody,
  ppRemoveBgBody: ppRemoveBgBody,
  ppMaskEditBody: ppMaskEditBody,
  ppGptImageBody: ppGptImageBody,
  ppSeedanceBody: ppSeedanceBody,
  setNodeModelFromPanel: setNodeModelFromPanel,
  runNodeFromPanel: runNodeFromPanel,
  toggleNodeBoxSelection: toggleNodeBoxSelection,
  clearBoxSelection: clearBoxSelection,
  updateRunSelectedBtn: updateRunSelectedBtn,
  runSelected: runSelected,
  getPortCenter: getPortCenter,
  hideContextMenu: hideContextMenu,
  runCanvas: runCanvas,
  runChain: runChain,
  toggleApprovalMode: toggleApprovalMode,
  updateApprovalButton: updateApprovalButton,
  approveNode: approveNode,
  rejectNode: rejectNode,
  startPolling: startPolling,
  stopPolling: stopPolling,
  updateNodeUI: updateNodeUI,
  renderApprovalActions: renderApprovalActions,
  removeApprovalActions: removeApprovalActions,
  checkAllDone: checkAllDone,
  getCompareOutputs: getCompareOutputs,
  showCompare: showCompare,
  closeCompare: closeCompare,
  openLightbox: openLightbox,
  closeLightbox: closeLightbox,
  scheduleMinimap: scheduleMinimap,
  getMinimapBounds: getMinimapBounds,
  updateMinimap: updateMinimap,
  onMinimapClick: onMinimapClick,
  autoSave: autoSave,
  saveCanvas: saveCanvas,
  newProject: newProject,
  cloneCanvas: cloneCanvas,
  startCanvasPolling: startCanvasPolling,
  showToast: showToast,
  stopCanvasPolling: stopCanvasPolling,
});
