    // ═══════════════════════════════════════════════════════════════
    // API Key 访问控制
    // ═══════════════════════════════════════════════════════════════
    const _apiKey = (() => {
      // 优先 URL param → localStorage → prompt
      const fromUrl = new URLSearchParams(location.search).get('api_key');
      if (fromUrl) { localStorage.setItem('api_key', fromUrl); return fromUrl; }
      return localStorage.getItem('api_key') || '';
    })();
    function _apiHeaders(headers = {}) {
      if (_apiKey) headers['X-API-Key'] = _apiKey;
      return headers;
    }
    async function _apiFetch(url, opts = {}) {
      opts.headers = Object.assign(opts.headers || {}, _apiHeaders());
      const r = await fetch(url, opts);
      if (r.status === 401 && !localStorage.getItem('api_key')) {
        const key = prompt('请输入 API Key：');
        if (key) { localStorage.setItem('api_key', key); location.reload(); }
      }
      return r;
    }

    // ═══════════════════════════════════════════════════════════════
    // 数据模型
    // ═══════════════════════════════════════════════════════════════
    let canvasData = { nodes: [], connections: [] };
    let selectedNode = null, selectedConn = null;
    let selectedNodes = new Set();  // Shift+框选/点选的多选集合（区别于单选 selectedNode）
    let currentCanvasId = null;
    const pollTimers = {};
    const nodeElements = {};
    let nodeRuntime = {};  // {nodeId: {status, progress, image_url}} 运行态，不持久化
    let clipboardGraph = null;  // {nodes: [...], connections: [...]} 复制粘贴剪贴板

    let viewX = 100, viewY = 70, viewScale = 1;
    let isPanning = false, panStart = null;
    let isConnecting = false, connStart = null;
    // 框选状态
    let isBoxSelecting = false, boxStart = null, boxEnd = null, boxSelectMoved = false;
    let suppressNextBlankClick = false;  // 框选 mouseup 后抑制紧随的 click 清空

    const NODE_CFG = {
      image_input:      { icon: 'image',   title: '图片输入',          color: 'var(--c-image_input)' },
      gpt_image:        { icon: 'spark',   title: 'AI 生图',           color: 'var(--c-gpt_image)' },
      remove_bg:        { icon: 'scissors',title: '抠图',              color: 'var(--c-remove_bg)' },
      mask_edit:        { icon: 'brush',   title: '遮罩编辑',          color: 'var(--c-mask_edit)' },
      seedance_video:   { icon: 'video',   title: '视频生成',          color: 'var(--c-seedance)' },
    };
    const STATUS_LABELS = { idle:'待机', pending:'排队', running:'运行中', success:'完成', failed:'失败', blocked:'阻断' };

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
        case 'gpt_image': return { prompt:'', hair_url:'', makeup:'', clothing_url:'', model:'gpt-image-2', size:'1024x1024', image2_url:'', image3_url:'', image4_url:'' };
        case 'remove_bg': return {};
        case 'mask_edit': return { mask_url: null };
        case 'seedance_video': return { prompt:'', duration:'8', aspect_ratio:'9:16', channel:'official' };
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
        label: 'RH gpt-image 图生图',
        resolutions: ['1k', '2k', '4k'],
        defaultRes: '1k',
        aspectRatios: ['9:16', '16:9', '1:1', '4:3', '3:4', '4:5'],
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
      selectedNode = null; currentCanvasId = null;
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
    function cloneChain() {
      if (!selectedNode) { alert('请先选中一条链路中的任意节点'); return; }
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
            to: idMap[c.to]
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
      el.className = 'node' + (node.type === 'gpt_image' || node.type === 'seedance_video' ? ' gen-node' : '');
      if (selectedNodes.has(node.id)) el.classList.add('box-selected');
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
      const inPort = node.type === 'image_input' ? '' : '<div class="port port-in" data-port="in"></div>';
      const outPort = '<div class="port port-out" data-port="out"></div>';
      const iconSvg = cfg.icon ? `<svg class="node-icon-svg"><use href="#icon-${cfg.icon}"/></svg>` : '';
      return `${inPort}${outPort}
        <button class="node-delete" onclick="removeNode('${node.id}')">✕</button>
        <div class="node-header" data-id="${node.id}">
          <span class="node-icon">${iconSvg}</span>
          <span class="node-title">${cfg.title}</span>
          <span class="node-badge" id="badge-${node.id}">待机</span>
        </div>
        <div class="node-body">${buildNodeBody(node)}</div>`;
    }
    function buildNodeBody(node) {
      const d = node.data;
      let html = '';
      if (d.image_url) {
        html += `<div class="node-preview" onclick="openLightbox('${d.image_url}')"><div class="checkerboard"></div><img src="${d.image_url}" /></div>`;
      } else {
        html += `<div class="node-preview"><div class="checkerboard"></div><span class="preview-placeholder"></span></div>`;
      }
      if (d._width && d._height) {
        html += `<div class="node-dim">${d._width} x ${d._height}</div>`;
      }
      if (node.type === 'image_input') {
        html += `<div style="display:flex;gap:4px;align-items:center">
          <label class="upload-btn" for="upload-${node.id}"><span>上传图片</span></label>
          ${d.image_url ? `<button class="ref-clear" onclick="clearNodeField('${node.id}','image_url')">清除</button>` : ''}
        </div>
          <input id="upload-${node.id}" type="file" accept="image/*" style="display:none" onchange="uploadImage('${node.id}',this)" />`;
      } else if (node.type === 'gpt_image') {
        const model = d.model || 'gpt-image-2';
        const cfg = AI_IMAGE_MODEL_CFG[model] || AI_IMAGE_MODEL_CFG['gpt-image-2'];
        const thumb = d.image_url ? `<img src="${d.image_url}" onclick="openLightbox('${d.image_url}')" style="cursor:pointer" />` : `<span class="gen-thumb-empty">?</span>`;
        const prompt = d.prompt || getDefaultImagePrompt();
        const isGptImage2 = model === 'gpt-image-2';
        const size = d.size || d.resolution || cfg.defaultSize || '1024x1024';
        const ar = d.aspect_ratio || cfg.defaultAspect;
        const res = d.resolution || cfg.defaultRes;
        const modelOptions = Object.entries(AI_IMAGE_MODEL_CFG).map(([k,v]) =>
          `<option value="${k}" ${k===model?'selected':''}>${v.label}</option>`
        ).join('');
        const sizeOptions = (cfg.sizes || []).map(s =>
          `<option value="${s}" ${s===size?'selected':''}>${s}</option>`
        ).join('');
        const resOptions = (cfg.resolutions || []).map(r =>
          `<option value="${r}" ${r===res?'selected':''}>${r}</option>`
        ).join('');
        const arOptions = (cfg.aspectRatios || []).map(a =>
          `<option value="${a}" ${a===ar?'selected':''}>${a}</option>`
        ).join('');
        const refSlot = (field, label) => `
          <div style="flex:1;position:relative">
            <div class="node-label">${label}</div>
            <div class="ref-upload" ${d[field] ? `onclick="event.stopPropagation();openLightbox('${d[field]}')"` : `onclick="document.getElementById('upload-${field}-${node.id}').click()"`}>
              ${d[field] ? `<img src="${d[field]}" />` : `<span class="ref-upload-empty">+ 上传</span>`}
            </div>
            ${d[field] ? `<button class="ref-clear" onclick="event.stopPropagation();clearNodeField('${node.id}','${field}')">&times;</button>` : ''}
            <input id="upload-${field}-${node.id}" type="file" accept="image/*" style="display:none" onchange="uploadRefImage('${node.id}','${field}',this)" />
          </div>`;
        let refSlotsHtml = '';
        if (model === 'gpt-image-2') {
          refSlotsHtml = `<div style="display:flex;gap:5px;margin-top:4px">${refSlot('hair_url','参考图2 · 发型')}${refSlot('clothing_url','参考图3 · 服装')}</div><div style="font-size:9px;color:#94A3B8;padding:2px 4px">图1=主体图（来自上游），按顺序传入</div>`;
        } else if (model === 'rh_gpt_image_i2i') {
          refSlotsHtml = `<div style="display:flex;gap:5px;margin-top:4px">${refSlot('image2_url','参考图2')}</div>`;
        } else if (model === 'nano_banana_2') {
          refSlotsHtml = `<div style="display:flex;gap:5px;margin-top:4px">${refSlot('image2_url','参考图2')}${refSlot('image3_url','参考图3')}${refSlot('image4_url','参考图4')}</div>`;
        }
        html += `
          <div class="gen-prompt-box">
            <div class="gen-thumb">${thumb}</div>
            <div class="gen-textarea-wrap">
              <textarea placeholder="输入提示词..." oninput="updateNodeData('${node.id}','prompt',this.value); updateCharCount(this)">${prompt}</textarea>
              <div class="gen-char-count">${prompt.length} / 2500</div>
            </div>
          </div>
          <div class="gen-toolbar">
            <select class="gen-model" onchange="setNodeModel('${node.id}',this.value)">
              ${modelOptions}
            </select>
            ${isGptImage2 ? `
              <select class="gen-ratio" onchange="updateNodeData('${node.id}','size',this.value)">
                ${sizeOptions}
              </select>` : `
              <select class="gen-ratio" onchange="updateNodeData('${node.id}','aspect_ratio',this.value)">
                ${arOptions}
              </select>
              <select class="gen-ratio" onchange="updateNodeData('${node.id}','resolution',this.value)">
                ${resOptions}
              </select>`}
            <div class="spacer"></div>
            <button class="magic-btn" onclick="polishPrompt('${node.id}')">润色</button>
            <div class="cost">${cfg.cost}</div>
          </div>
          ${refSlotsHtml}`;
      } else if (node.type === 'mask_edit') {
        if (d.mask_url) {
          html += `<div class="node-preview" onclick="openLightbox('${d.mask_url}')"><div class="checkerboard"></div><img src="${d.mask_url}" /></div>`;
        }
        html += `<div style="font-size:11px;color:var(--c-mask_edit);padding:4px 6px;background:rgba(236,72,153,0.06);border-radius:5px;text-align:center;">双击编辑遮罩</div>`;
      } else if (node.type === 'seedance_video') {
        const thumb = d.video_url ? `<video src="${d.video_url}" muted loop class="gen-thumb-video" onclick="event.stopPropagation();openLightbox('${d.video_url}',true)"></video>` : d.image_url ? `<img src="${d.image_url}" onclick="openLightbox('${d.image_url}')" style="cursor:pointer" />` : `<span class="gen-thumb-empty">?</span>`;
        const prompt = d.prompt || getDefaultVideoPrompt();
        html += `
          <div class="gen-prompt-box">
            <div class="gen-thumb">${thumb}</div>
            <div class="gen-textarea-wrap">
              <textarea placeholder="输入视频描述..." oninput="updateNodeData('${node.id}','prompt',this.value); updateCharCount(this)">${prompt}</textarea>
              <div class="gen-char-count">${prompt.length} / 2500</div>
            </div>
          </div>
          <div class="gen-toolbar">
            <select class="gen-model" onchange="updateNodeData('${node.id}','channel',this.value)">
              <option value="official">seedance（官方稳定版）</option>
              <option value="low_cost">seedance（低价版）</option>
            </select>
            <select class="gen-ratio" onchange="updateNodeData('${node.id}','aspect_ratio',this.value)">
              <option value="9:16" ${d.aspect_ratio!=='16:9'?'selected':''}>9:16 · 自适应</option>
              <option value="16:9" ${d.aspect_ratio==='16:9'?'selected':''}>16:9 · 自适应</option>
            </select>
            <select class="gen-duration" onchange="updateNodeData('${node.id}','duration',this.value)">
              <option value="4" ${d.duration==='4'?'selected':''}>4秒</option>
              <option value="8" ${d.duration==='8'||!d.duration?'selected':''}>8秒</option>
              <option value="10" ${d.duration==='10'?'selected':''}>10秒</option>
              <option value="12" ${d.duration==='12'?'selected':''}>12秒</option>
              <option value="15" ${d.duration==='15'?'selected':''}>15秒</option>
            </select>
            <div class="spacer"></div>
            <div class="cost">≈0.08元</div>
          </div>`;
      }

      html += `<div class="node-progress-bar"><div class="fill" id="prog-${node.id}" style="width:0%"></div></div>`;
      if (d._error) html += `<div style="font-size:10px;color:#F87171;padding:3px 5px;background:rgba(239,68,68,0.06);border-radius:4px;">${d._error}</div>`;
      return html;
    }
    function updateNodeData(id, field, val) { const n = canvasData.nodes.find(n=>n.id===id); if(n) n.data[field]=val; autoSave(); }
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
      if (!cfg.resolutions.includes(node.data.resolution)) node.data.resolution = cfg.defaultRes;
      if (!cfg.aspectRatios.includes(node.data.aspect_ratio)) node.data.aspect_ratio = cfg.defaultAspect;
    }
    function refreshNodeBody(nodeId) {
      const node = canvasData.nodes.find(n => n.id === nodeId);
      if (!node) return;
      const el = nodeElements[nodeId];
      if (!el) return;
      el.querySelector('.node-body').innerHTML = buildNodeBody(node);
      bindNodeEvents(el, node);
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
        if (!cfg.aspectRatios.includes(node.data.aspect_ratio)) {
          node.data.aspect_ratio = cfg.defaultAspect;
        }
        if (!cfg.resolutions.includes(node.data.resolution)) {
          node.data.resolution = cfg.defaultRes;
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
      el.querySelector('.node-body').innerHTML = buildNodeBody(node);
      const ta = el.querySelector('textarea');
      if (ta) { setTimeout(() => { updateCharCount(ta); }, 0); }
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
      } catch(e) { alert('上传失败: '+e.message); }
    }
    async function uploadRefImage(nodeId, field, input) {
      const file = input.files[0]; if(!file) return;
      const fd = new FormData(); fd.append('file', file);
      try {
        const r = await _apiFetch('/api/assets/upload', { method:'POST', body:fd });
        const d = await r.json();
        const node = canvasData.nodes.find(n=>n.id===nodeId);
        if (node) { node.data[field] = d.url; refreshNodePreview(nodeId); autoSave(); }
      } catch(e) { alert('上传失败: '+e.message); }
      input.value = '';
    }
    function clearNodeField(nodeId, field) {
      const node = canvasData.nodes.find(n => n.id === nodeId);
      if (!node) return;
      node.data[field] = '';
      refreshNodePreview(nodeId);
      autoSave();
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
      const upstreamConn = canvasData.connections.find(c => c.to === nodeId);
      let imageUrl = node.data.image_url;
      if (!imageUrl && upstreamConn) {
        const upstreamNode = canvasData.nodes.find(n => n.id === upstreamConn.from);
        if (upstreamNode) imageUrl = upstreamNode.data.image_url;
      }
      if (!imageUrl) { alert('请先连线上游图片输入节点'); return; }
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
        } catch(e) { alert('遮罩上传失败: ' + e.message); }
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
        const x1 = fn.x + fe.offsetWidth, y1 = fn.y + fe.offsetHeight/2;
        const x2 = tn.x, y2 = tn.y + te.offsetHeight/2;
        const dx = Math.max(40, Math.abs(x2-x1)*0.35);
        const p = `M ${x1} ${y1} C ${x1+dx} ${y1}, ${x2-dx} ${y2}, ${x2} ${y2}`;
        const el = document.createElementNS('http://www.w3.org/2000/svg','path');
        el.setAttribute('d', p);
        let cls = 'conn-path';
        if (selectedConn === conn.id) cls += ' selected';
        // 运行中的连线动画
        if (currentCanvasId) {
          const rec = pollTimers[conn.from];
          if (rec) cls += ' running';
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
      const header = el.querySelector('.node-header');
      header.addEventListener('mousedown', (e) => {
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
      const outPort = el.querySelector('.port-out');
      if (outPort) {
        outPort.addEventListener('mousedown', (e) => {
          e.stopPropagation(); e.preventDefault();
          isConnecting = true; connStart = node.id;
        });
      }
      el.addEventListener('mousedown', (e) => {
        if (e.target.classList.contains('port') || e.target.closest('.node-header')) return;
        if (e.shiftKey) { e.stopPropagation(); e.preventDefault(); toggleNodeBoxSelection(node.id); return; }
        selectedNode = node.id;
        clearBoxSelection();
        updateRunSelectedBtn();
        document.querySelectorAll('.node.selected').forEach(n => n.classList.remove('selected'));
        el.classList.add('selected');
      });
      if (node.type === 'mask_edit') {
        el.addEventListener('dblclick', (e) => {
          e.stopPropagation();
          openMaskEditor(node.id);
        });
      }
    }

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
        btn.textContent = '运行当前链路';
        btn.disabled = false;
      } else {
        btn.textContent = '运行选中 (0)';
        btn.disabled = true;
      }
    }

    function runSelected() {
      if (selectedNodes.size > 0) {
        runCanvas([...selectedNodes]);
      } else if (selectedNode) {
        runCanvas([...getChainNodeIds(selectedNode)]);
      } else {
        alert('请先选择节点（单击选中运行链路，或 Shift+框选运行部分）');
      }
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
            canvasData.connections.push({ id: uid(), from: idMap[c.from], to: idMap[c.to] });
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
        const fn = canvasData.nodes.find(n=>n.id===connStart);
        const fe = nodeElements[connStart];
        if (!fn || !fe) return;
        const x1 = fn.x+fe.offsetWidth, y1 = fn.y+fe.offsetHeight/2;
        const r = viewport.getBoundingClientRect();
        const c = screenToCanvas(e.clientX-r.left, e.clientY-r.top);
        const dx = Math.max(40, Math.abs(c.x-x1)*0.35);
        const p = `M ${x1} ${y1} C ${x1+dx} ${y1}, ${c.x-dx} ${c.y}, ${c.x} ${c.y}`;
        let t = document.getElementById('svg-layer').querySelector('.conn-temp');
        if (!t) { t = document.createElementNS('http://www.w3.org/2000/svg','path'); t.setAttribute('class','conn-temp'); document.getElementById('svg-layer').appendChild(t); }
        t.setAttribute('d', p);
      }
    });
    document.addEventListener('mouseup', (e) => {
      if (isConnecting && connStart) {
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
    async function runCanvas(nodeIds) {
      // nodeIds 可选：不传=运行全部；传=只运行该子集节点 + 子集内连线（独立链路）
      let nodes = canvasData.nodes, conns = canvasData.connections;
      if (nodeIds && nodeIds.length) {
        const idSet = new Set(nodeIds);
        nodes = canvasData.nodes.filter(n => idSet.has(n.id));
        conns = canvasData.connections.filter(c => idSet.has(c.from) && idSet.has(c.to));
      }
      if (nodes.length === 0) { alert('没有可运行的节点'); return; }
      Object.keys(pollTimers).forEach(stopPolling);
      const r = await _apiFetch('/api/canvas/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          nodes: nodes.map(n => ({ id:n.id, type:n.type, x:n.x, y:n.y, data:n.data })),
          connections: conns.map(c => ({ id:c.id, from:c.from, to:c.to }))
        })
      });
      const d = await r.json();
      currentCanvasId = d.canvas_id;
      nodeRuntime = {};
      for (const n of nodes) { nodeRuntime[n.id] = { status:'pending', progress:0 }; startPolling(n.id); }
      updateStatusbar('running');
    }
    function runChain() {
      if (!selectedNode) { alert('请先选中要运行的链路中的任意节点'); return; }
      runCanvas([...getChainNodeIds(selectedNode)]);
    }

    function startPolling(nodeId) {
      if (pollTimers[nodeId]) clearInterval(pollTimers[nodeId]);
      pollTimers[nodeId] = setInterval(async () => {
        if (!currentCanvasId) return;
        try {
          const r = await _apiFetch(`/api/canvas/${currentCanvasId}/nodes/${nodeId}`);
          if (!r.ok) return;
          const d = await r.json();
          updateNodeUI(nodeId, d);
          if (['success','failed','blocked'].includes(d.status)) { stopPolling(nodeId); checkAllDone(); }
        } catch(e) {}
      }, 800);
    }
    function stopPolling(nodeId) { if (pollTimers[nodeId]) { clearInterval(pollTimers[nodeId]); delete pollTimers[nodeId]; renderConnections(); } }
    function updateNodeUI(nodeId, d) {
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
    }
    function checkAllDone() {
      if (Object.keys(pollTimers).length === 0) {
        updateStatusbar('done');
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
      const name = prompt('画布名称：', '我的画布');
      if (!name) return;
      const r = await _apiFetch('/api/canvas/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          nodes: canvasData.nodes.map(n => ({ id:n.id, type:n.type, x:n.x, y:n.y, data:n.data })),
          connections: canvasData.connections.map(c => ({ id:c.id, from:c.from, to:c.to }))
        })
      });
      const d = await r.json();
      alert(`已保存：${d.name}（${d.id}）`);
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

    function switchMode(mode) {
      const vp = document.getElementById('viewport');
      const ops = document.getElementById('ops-view');
      const btn = document.getElementById('mode-toggle');
      if (mode === 'ops') {
        vp.style.display = 'none';
        ops.style.display = 'block';
        btn.textContent = '高级画布';
        btn.onclick = () => switchMode('canvas');
        btn.style.background = 'rgba(167,139,250,0.12)';
        loadBatchHistory();
        btn.style.color = '#A78BFA';
        btn.style.borderColor = 'rgba(167,139,250,0.25)';
        loadStreamers();
        loadTemplates();
      } else {
        vp.style.display = 'block';
        ops.style.display = 'none';
        btn.textContent = '运营模式';
        btn.onclick = () => switchMode('ops');
        btn.style.background = 'rgba(74,158,255,0.12)';
        btn.style.color = '#4A9EFF';
        btn.style.borderColor = 'rgba(74,158,255,0.25)';
      }
    }

    // ─── 主播库 ───
    function toggleAddStreamerForm() {
      const f = document.getElementById('add-streamer-form');
      f.style.display = f.style.display === 'none' ? 'flex' : 'none';
      if (f.style.display === 'none') {
        opsState.newStreamerImageUrl = null;
        document.getElementById('new-streamer-name').value = '';
        document.getElementById('new-streamer-tag').value = '';
        document.getElementById('new-streamer-thumb').textContent = '+';
        document.getElementById('new-streamer-thumb').className = 'upload-thumb-empty';
      }
    }

    async function previewNewStreamer(input) {
      const file = input.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('file', file);
      const r = await _apiFetch('/api/assets/upload', { method: 'POST', body: fd });
      const d = await r.json();
      opsState.newStreamerImageUrl = d.url;
      const thumb = document.getElementById('new-streamer-thumb');
      thumb.innerHTML = `<img src="${d.url}" class="upload-thumb">`;
      thumb.className = '';
      thumb.style.cursor = 'pointer';
    }

    async function addStreamer() {
      const name = document.getElementById('new-streamer-name').value.trim();
      const tag = document.getElementById('new-streamer-tag').value.trim();
      const url = opsState.newStreamerImageUrl;
      if (!name) { alert('请输入主播名称'); return; }
      if (!url) { alert('请上传主播原图'); return; }
      const r = await _apiFetch('/api/streamers', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, source_image_url: url, tag })
      });
      if (r.ok) {
        toggleAddStreamerForm();
        loadStreamers();
      } else {
        alert('添加失败：' + await r.text());
      }
    }

    async function loadStreamers() {
      const r = await _apiFetch('/api/streamers');
      const d = await r.json();
      opsState.streamers = d.streamers || [];
      const list = document.getElementById('streamer-list');
      if (opsState.streamers.length === 0) {
        list.innerHTML = '<div class="ops-empty">暂无主播，点击右上角添加</div>';
        return;
      }
      list.innerHTML = opsState.streamers.map(s => `
        <div class="streamer-item" onclick="toggleSelectStreamer('${s.id}')">
          ${s.avatar_url
            ? `<img class="avatar" src="${s.avatar_url}">`
            : `<div class="avatar-placeholder">·</div>`}
          <div class="si-info">
            <div class="si-name">${escapeHtml(s.name)}</div>
            ${s.tag ? `<div class="si-tag">${escapeHtml(s.tag)}</div>` : ''}
          </div>
          <div class="si-del" onclick="deleteStreamer(event,'${s.id}')" title="删除">×</div>
        </div>
      `).join('');
    }

    function toggleSelectStreamer(sid) {
      const i = opsState.selectedStreamers.indexOf(sid);
      if (i >= 0) opsState.selectedStreamers.splice(i, 1);
      else opsState.selectedStreamers.push(sid);
      document.querySelectorAll('.streamer-item').forEach(el => el.classList.remove('selected'));
      opsState.selectedStreamers.forEach(id => {
        const el = [...document.querySelectorAll('.streamer-item')].find(e => e.getAttribute('onclick').includes(id));
        if (el) el.classList.add('selected');
      });
      updateSelectedChips();
      updateTotalCands();
    }

    function updateSelectedChips() {
      const bar = document.getElementById('selected-chips');
      if (opsState.selectedStreamers.length === 0) {
        bar.innerHTML = '<span style="color:#5a6573;font-size:12px">点击左侧主播库勾选（可多选）</span>';
        return;
      }
      bar.innerHTML = opsState.selectedStreamers.map(sid => {
        const s = opsState.streamers.find(x => x.id === sid);
        if (!s) return '';
        return `<span class="selected-chip">
          ${s.avatar_url ? `<img src="${s.avatar_url}">` : ''}
          ${escapeHtml(s.name)}
          <span class="remove" onclick="event.stopPropagation();toggleSelectStreamer('${s.id}')">×</span>
        </span>`;
      }).join('');
    }

    function updateTotalCands() {
      const n = opsState.candidateNum || 3;
      const total = opsState.selectedStreamers.length * n;
      document.getElementById('total-cands').textContent = total;
    }

    function adjustCandidates(delta) {
      let n = opsState.candidateNum || 3;
      n = Math.max(1, Math.min(6, n + delta));
      opsState.candidateNum = n;
      document.getElementById('candidate-num').textContent = n;
      updateTotalCands();
    }

    async function deleteStreamer(event, sid) {
      event.stopPropagation();
      if (!confirm('确认删除该主播？')) return;
      const r = await _apiFetch(`/api/streamers/${sid}`, { method: 'DELETE' });
      if (r.ok) loadStreamers();
    }

    // ─── 模板库 ───
    async function loadTemplates() {
      const r = await _apiFetch('/api/templates');
      const d = await r.json();
      opsState.templates = d.templates || [];
      const grid = document.getElementById('tpl-grid');
      const hint = document.getElementById('tpl-hint');
      if (opsState.templates.length === 0) {
        hint.style.display = 'block';
        grid.innerHTML = '';
        return;
      }
      hint.style.display = 'none';
      grid.innerHTML = opsState.templates.map(t => `
        <div class="tpl-card ${t.id === opsState.selectedTemplateId ? 'selected' : ''}"
             onclick="selectTemplate('${t.id}')">
          ${t.thumbnail_url ? `<img src="${t.thumbnail_url}" style="width:100%;height:60px;object-fit:cover;border-radius:4px 4px 0 0">` : ''}
          <div class="tc-name">${escapeHtml(t.name)}</div>
          <div class="tc-meta">${t.node_count} 节点${t.saved_at ? ' · ' + new Date(t.saved_at*1000).toLocaleDateString('zh-CN') : ''}</div>
          ${t.category ? `<span class="tc-cat">${escapeHtml(t.category)}</span>` : ''}
        </div>
      `).join('');
    }

    function selectTemplate(tid) {
      opsState.selectedTemplateId = tid;
      document.querySelectorAll('.tpl-card').forEach(el => el.classList.remove('selected'));
      const el = [...document.querySelectorAll('.tpl-card')].find(e => e.getAttribute('onclick').includes(tid));
      if (el) el.classList.add('selected');
    }

    async function saveAsTemplate() {
      if (canvasData.nodes.length === 0) { alert('画布为空，请先搭建节点链路'); return; }
      const name = prompt('模板名称：', '');
      if (!name) return;
      const category = prompt('分类（如 服装风格/场景，可留空）：', '') || '';
      const r = await _apiFetch('/api/templates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name, category,
          nodes: canvasData.nodes.map(n => ({ id:n.id, type:n.type, x:n.x, y:n.y, data:n.data })),
          connections: canvasData.connections.map(c => ({ id:c.id, from:c.from, to:c.to }))
        })
      });
      const d = await r.json();
      alert(`已存为模板：${d.name}`);
    }

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    // ═══════════════════════════════════════════════════════════════
    // 批量生产：启动 + 单接口轮询 + 候选网格渲染
    // ═══════════════════════════════════════════════════════════════
    let batchPollTimer = null;
    let currentBatchId = null;
    let currentBatchData = null;

    async function loadBatchHistory() {
      try {
        const r = await _apiFetch('/api/batch/list');
        const list = await r.json();
        const sel = document.getElementById('batch-history-select');
        if (!sel) return;
        sel.innerHTML = '<option value="">-- 历史批次 --</option>';
        for (const b of list) {
          const t = new Date(b.created_at * 1000).toLocaleString();
          sel.innerHTML += `<option value="${b.id}">${b.template_name || b.id.slice(0,8)} | ${b.status} | ${b.streamer_count}主播 | ${t}</option>`;
        }
      } catch (e) { /* ignore */ }
    }

    function selectBatchFromHistory(selectEl) {
      const id = selectEl.value;
      if (!id) return;
      currentBatchId = id;
      document.getElementById('candidate-panel').style.display = 'block';
      startBatchPolling(id);
    }

    async function startBatch() {
      if (!opsState.selectedTemplateId) { alert('请先在步骤1选择模板'); return; }
      if (opsState.selectedStreamers.length === 0) { alert('请先在主播库勾选主播'); return; }
      const n = opsState.candidateNum || 3;
      const btn = document.getElementById('start-batch-btn');
      btn.disabled = true; btn.textContent = '启动中...';
      try {
        const r = await _apiFetch('/api/batch/run', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            template_id: opsState.selectedTemplateId,
            streamer_ids: opsState.selectedStreamers,
            candidates_per_streamer: n,
          })
        });
        const d = await r.json();
        currentBatchId = d.batch_id;
        document.getElementById('candidate-panel').style.display = 'block';
        document.getElementById('step4-num').classList.add('active');
        btn.textContent = '生成中...';
        startBatchPolling(d.batch_id);
      } catch (e) {
        alert('启动失败：' + e.message);
        btn.disabled = false; btn.textContent = '开始批量生成';
      }
    }

    function startBatchPolling(batchId) {
      if (batchPollTimer) clearInterval(batchPollTimer);
      const poll = async () => {
        try {
          const r = await _apiFetch(`/api/batch/${batchId}`);
          const batch = await r.json();
          currentBatchData = batch;
          renderBatch(batch);
          // 停止条件：phase1 完成且无视频运行中
          const hasVideoRunning = (batch.items || []).some(it =>
            ['pending', 'running', 'idle'].includes(it.video_status)
          );
          if (batch.status === 'done' && !hasVideoRunning) {
            clearInterval(batchPollTimer);
            batchPollTimer = null;
            const btn = document.getElementById('start-batch-btn');
            btn.disabled = false; btn.textContent = '开始批量生成';
          }
        } catch (e) { console.error('poll error', e); }
      };
      poll();
      batchPollTimer = setInterval(poll, 2000);
    }

    function renderBatch(batch) {
      const stats = batch.stats || { total:0, success:0, running:0, failed:0 };
      // 右栏：任务进度
      const progBody = document.getElementById('batch-progress-body');
      const pct = stats.total > 0 ? Math.round((stats.success + stats.failed) / stats.total * 100) : 0;
      document.getElementById('batch-status-badge').textContent =
        batch.status === 'done' ? '已完成' : '运行中';
      progBody.innerHTML = `
        <div style="display:flex;align-items:end;gap:6px;margin-bottom:4px">
          <span style="font-size:24px;font-weight:700;color:#e6edf3">${stats.success + stats.failed}</span>
          <span style="font-size:13px;color:#8b97a7;margin-bottom:4px">/ ${stats.total} 张</span>
        </div>
        <div class="batch-progress-bar"><div class="fill" style="width:${pct}%"></div></div>
        <div class="progress-stats">
          <div class="progress-stat success"><div class="num">${stats.success}</div><div class="label">成功</div></div>
          <div class="progress-stat running"><div class="num">${stats.running}</div><div class="label">进行中</div></div>
          <div class="progress-stat failed"><div class="num">${stats.failed}</div><div class="label">失败</div></div>
        </div>
      `;

      // 右栏：错误汇总
      const errBody = document.getElementById('batch-errors-body');
      const failedCands = [];
      (batch.items || []).forEach(item => {
        (item.candidates || []).forEach(c => {
          if (c.status === 'failed') failedCands.push({ ...c, streamer_name: item.streamer_name, streamer_avatar: item.streamer_avatar });
        });
      });
      if (failedCands.length === 0) {
        errBody.innerHTML = '<div class="ops-empty">无</div>';
      } else {
        errBody.innerHTML = failedCands.map(c => `
          <div class="error-item">
            <div class="ei-head">
              ${c.streamer_avatar ? `<img src="${c.streamer_avatar}">` : ''}
              <span class="ei-name">${escapeHtml(c.streamer_name)} · ${c.node_id}</span>
            </div>
            <div class="ei-msg">${escapeHtml(c.error || '未知错误')}</div>
          </div>
        `).join('');
      }

      // 中栏：候选网格
      const container = document.getElementById('candidate-grid-container');
      const statusText = document.getElementById('candidate-status-text');
      statusText.textContent = batch.status === 'done'
        ? `完成 ${stats.success + stats.failed}/${stats.total}`
        : `生成中 ${stats.success + stats.failed}/${stats.total}`;
      container.innerHTML = (batch.items || []).map(item => {
        const cands = (item.candidates || []).map((c, idx) => {
          const statusLabel = { idle:'等待', pending:'排队', running:'生成中', success:'', failed:'失败', interrupted:'中断' }[c.status] || c.status;
          let inner;
          if (c.status === 'success' && c.image_url) {
            inner = `<img src="${c.image_url}"><div class="cand-label">候选 ${idx+1}</div>`;
          } else if (c.status === 'failed' || c.status === 'interrupted') {
            inner = `<div class="cand-overlay">${statusLabel}<div class="progress-text">${escapeHtml((c.error||'').substring(0,40))}</div><button class="ops-btn small" onclick="event.stopPropagation();retryCandidate('${item.streamer_id}','${c.node_id}')">重试</button></div>`;
          } else {
            inner = `<div class="cand-overlay">${statusLabel}<div class="progress-text">${c.progress||0}%</div><div class="cand-progress-bar" style="width:${c.progress||0}%"></div></div>`;
          }
          const adoptedClass = item.adopted_node_id === c.node_id ? 'adopted' : '';
          return `<div class="cand-card ${c.status} ${adoptedClass}" onclick="adoptCandidate('${item.streamer_id}','${c.node_id}')">${inner}</div>`;
        }).join('');
        const adoptedCount = item.adopted_node_id ? 1 : 0;
        return `
          <div class="cand-group">
            <div class="cand-group-head">
              ${item.streamer_avatar ? `<img src="${item.streamer_avatar}">` : ''}
              <span class="cg-name">${escapeHtml(item.streamer_name)}</span>
              <span class="cg-status">${adoptedCount}/${item.candidates.length} 采用</span>
            </div>
            <div class="cand-grid">${cands}</div>
          </div>
        `;
      }).join('');

      // 中栏：步骤5 出片面板（仅在有人采用候选后显示）
      renderVideoPanel(batch);
    }

    // 步骤5 出片：每个已采用主播一行，手填 prompt + 生成视频 + 下载
    let videoPrompts = {}; // streamer_id -> prompt（保留用户输入，避免重渲染丢失）

    function renderVideoPanel(batch) {
      const panel = document.getElementById('video-panel');
      const container = document.getElementById('video-rows-container');
      const statusText = document.getElementById('video-status-text');

      const adoptedItems = (batch.items || []).filter(it => it.adopted_image_url);
      if (adoptedItems.length === 0) {
        panel.style.display = 'none';
        return;
      }
      panel.style.display = 'block';
      document.getElementById('step5-num').classList.add('active');

      const vStats = adoptedItems.reduce((acc, it) => {
        const st = it.video_status;
        if (st === 'success') acc.success++;
        else if (st === 'failed') acc.failed++;
        else if (['pending', 'running', 'idle'].includes(st)) acc.running++;
        return acc;
      }, { success:0, failed:0, running:0 });
      statusText.textContent = `视频 ${vStats.success}/${adoptedItems.length}` +
        (vStats.running > 0 ? ` · 生成中 ${vStats.running}` : '');

      // 焦点保护：用户正在编辑 prompt 时跳过重渲染，避免输入被打断
      const ae = document.activeElement;
      if (ae && ae.classList && ae.classList.contains('vr-prompt')) {
        // 仅更新状态徽章与按钮 disabled 状态，不重建 DOM
        adoptedItems.forEach(item => {
          const row = container.querySelector(`[data-sid="${item.streamer_id}"]`);
          if (!row) return;
          const statusEl = row.querySelector('.vr-status');
          if (statusEl) {
            const vst = item.video_status;
            const label = { idle:'待生成', pending:'排队', running:'生成中', success:'完成', failed:'失败' }[vst] || '待生成';
            statusEl.textContent = (vst === 'running' || vst === 'pending') ? `${label} ${item.video_progress||0}%` : label;
          }
        });
        return;
      }

      container.innerHTML = adoptedItems.map(item => {
        const vst = item.video_status;
        const label = { idle:'待生成', pending:'排队', running:'生成中', success:'完成', failed:'失败' }[vst] || '待生成';
        const statusClass = (vst === 'running' || vst === 'pending') ? 'running'
          : (vst === 'success' ? 'success' : (vst === 'failed' ? 'failed' : ''));
        const isRunning = (vst === 'running' || vst === 'pending');
        const progress = item.video_progress || 0;
        const promptVal = videoPrompts[item.streamer_id] !== undefined ? videoPrompts[item.streamer_id] : '';

        let actions;
        if (vst === 'success' && item.video_url) {
          actions = `
            <a class="vr-link" href="${item.video_url}" target="_blank">下载视频</a>
            <a class="vr-link" href="${item.adopted_image_url}" target="_blank">查看采用图</a>`;
        } else if (isRunning) {
          actions = `
            <button class="ops-btn small" disabled>生成中</button>
            <div class="vr-status ${statusClass}">${label} ${progress}%</div>
            <div class="vr-bar"><div class="fill" style="width:${progress}%"></div></div>`;
        } else if (vst === 'failed') {
          actions = `
            <button class="ops-btn small" onclick="startVideo('${item.streamer_id}')">重试</button>
            <div class="vr-status ${statusClass}">${label}</div>`;
        } else {
          actions = `
            <button class="ops-btn primary small" onclick="startVideo('${item.streamer_id}')">生成视频</button>
            <div class="vr-status ${statusClass}">${label}</div>`;
        }

        return `
          <div class="video-row" data-sid="${item.streamer_id}">
            ${item.streamer_avatar ? `<img class="vr-avatar" src="${item.streamer_avatar}">` : '<div class="vr-avatar"></div>'}
            <div class="vr-name" title="${escapeHtml(item.streamer_name)}">${escapeHtml(item.streamer_name)}</div>
            <textarea class="vr-prompt" placeholder="视频 prompt：描述运镜/动作/时长（建议 30-100 字）"
              oninput="videoPrompts['${item.streamer_id}']=this.value"
              ${isRunning ? 'disabled' : ''}>${escapeHtml(promptVal)}</textarea>
            <select id="video-duration-${item.streamer_id}" style="font-size:11px;padding:2px 4px;border:1px solid #ddd;border-radius:4px" ${isRunning ? 'disabled' : ''}>
              <option value="4">4s</option><option value="8" selected>8s</option><option value="12">12s</option>
            </select>
            <select id="video-ar-${item.streamer_id}" style="font-size:11px;padding:2px 4px;border:1px solid #ddd;border-radius:4px" ${isRunning ? 'disabled' : ''}>
              <option value="9:16" selected>9:16</option><option value="16:9">16:9</option><option value="1:1">1:1</option>
            </select>
            <div class="vr-actions">${actions}</div>
          </div>`;
      }).join('');
    }

    async function startVideo(streamerId) {
      if (!currentBatchId) return;
      const prompt = (videoPrompts[streamerId] || '').trim();
      if (prompt.length < 5) {
        alert('请填写视频 prompt（至少 5 个字）');
        return;
      }
      // 读取视频参数（从对应主播行的 select）
      const durSel = document.getElementById(`video-duration-${streamerId}`);
      const arSel = document.getElementById(`video-ar-${streamerId}`);
      const duration = durSel ? durSel.value : '8';
      const aspect_ratio = arSel ? arSel.value : '9:16';
      try {
        const r = await _apiFetch(`/api/batch/${currentBatchId}/video`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ streamer_id: streamerId, prompt, duration, aspect_ratio })
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || r.statusText);
        }
        // 重启轮询以观察视频进度
        if (!batchPollTimer) startBatchPolling(currentBatchId);
      } catch (e) {
        alert('视频生成启动失败：' + e.message);
      }
    }

    async function retryCandidate(streamerId, nodeId) {
      if (!currentBatchId) return;
      try {
        const r = await _apiFetch(`/api/batch/${currentBatchId}/retry-candidate`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ streamer_id: streamerId, node_id: nodeId })
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || r.statusText);
        }
        // 重启轮询以观察重试进度
        if (!batchPollTimer) startBatchPolling(currentBatchId);
      } catch (e) {
        alert('重试启动失败：' + e.message);
      }
    }

    async function adoptCandidate(streamerId, nodeId) {
      if (!currentBatchId) return;
      const item = (currentBatchData.items || []).find(i => i.streamer_id === streamerId);
      if (!item) return;
      const cand = (item.candidates || []).find(c => c.node_id === nodeId);
      if (!cand || cand.status !== 'success') return;
      if (item.adopted_node_id === nodeId) return;
      if (item.adopted_node_id && !confirm('已采用过候选，确认改用这张？')) return;
      try {
        await _apiFetch(`/api/batch/${currentBatchId}/adopt`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ streamer_id: streamerId, node_id: nodeId })
        });
        item.adopted_node_id = nodeId;
        renderBatch(currentBatchData);
      } catch (e) { alert('采用失败：' + e.message); }
    }

    async function loadCanvasList() {
      const r = await _apiFetch('/api/canvas/list');
      const d = await r.json();
      const body = document.getElementById('canvas-list-body');
      if (d.canvases.length === 0) { body.innerHTML = '<div style="color:#555;font-size:12px;text-align:center;padding:20px">暂无已保存画布</div>'; }
      else {
        body.innerHTML = d.canvases.map(c => {
          const dt = new Date(c.saved_at * 1000).toLocaleString('zh-CN');
          return `<div class="canvas-item" onclick="loadCanvas('${c.id}')">
            <span style="width:14px;height:14px;display:inline-flex;align-items:center;justify-content:center;color:#777"><svg style="width:100%;height:100%"><use href="#icon-list"/></svg></span>
            <div class="ci-name">${c.name}</div>
            <div class="ci-meta">${c.node_count} 节点 · ${dt}</div>
            <button class="ci-delete" onclick="event.stopPropagation();deleteCanvas('${c.id}','${c.name}')" style="margin-left:auto;font-size:10px;color:#999;border:none;background:none;cursor:pointer;padding:2px 4px" title="删除">✕</button>
          </div>`;
        }).join('');
      }
      document.getElementById('canvas-modal').style.display = 'flex';
    }

    async function loadCanvas(id) {
      const r = await _apiFetch(`/api/canvas/${id}`);
      const d = await r.json();
      // 清空当前画布
      canvasData.nodes.forEach(n => stopPolling(n.id));
      Object.values(nodeElements).forEach(el => el.remove());
      Object.keys(nodeElements).forEach(k => delete nodeElements[k]);
      // 加载新画布
      canvasData = { nodes: d.nodes || [], connections: d.connections || [] };
      canvasData.nodes.forEach(migrateNodeData);
      canvasData.nodes.forEach(renderNode);
      renderConnections();
      updateStatusbar();
      undoStack = []; redoStack = []; updateUndoRedoButtons();
      closeModal();
      autoSave();
    }

    function closeModal() { document.getElementById('canvas-modal').style.display = 'none'; }

    async function deleteCanvas(id, name) {
      if (!confirm(`确定删除画布 "${name}"？`)) return;
      try {
        await _apiFetch(`/api/canvas/${id}`, { method: 'DELETE' });
        loadCanvasList(); // 刷新列表
      } catch (e) {
        alert('删除失败：' + e.message);
      }
    }

    // ═══════════════════════════════════════════════════════════════
    // 状态栏
    // ═══════════════════════════════════════════════════════════════
    function updateStatusbar(state) {
      document.getElementById('sb-nodes').textContent = canvasData.nodes.length;
      document.getElementById('sb-conns').textContent = canvasData.connections.length;
      const dot = document.getElementById('sb-dot'), st = document.getElementById('sb-status');
      dot.className = 'sb-dot';
      if (state === 'running') { dot.classList.add('running'); st.textContent = '运行中...'; }
      else if (state === 'done') { st.textContent = '全部完成'; }
      else { st.textContent = '就绪'; }
    }

    // ═══════════════════════════════════════════════════════════════
    // 初始化
    // ═══════════════════════════════════════════════════════════════
    applyTransform();
    updateStatusbar();

    // 从 localStorage 恢复自动保存的画布
    const saved = localStorage.getItem('autosave');
    if (saved) {
      try {
        const d = JSON.parse(saved);
        if (d.nodes && d.nodes.length > 0) {
          canvasData = d;
          canvasData.nodes.forEach(migrateNodeData);
          canvasData.nodes.forEach(renderNode);
          renderConnections();
          updateStatusbar();
        }
      } catch(e) {}
    }

    // 如果没有自动保存，放示例节点引导用户
    if (canvasData.nodes.length === 0) {
      addNodeAt('image_input', 260, 250);
      addNodeAt('gpt_image', 760, 250);
      renderConnections();
      updateStatusbar();
      undoStack = []; redoStack = []; updateUndoRedoButtons();
    }

    window.addEventListener('resize', () => renderConnections());
    window.addEventListener('beforeunload', () => {
      localStorage.setItem('autosave', JSON.stringify(canvasData));
    });
