// ═══ 项目抽屉与画布列表（project.js）═══
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
            <div class="ci-actions" style="margin-left:auto;display:flex;gap:6px">
              <button class="ci-action" onclick="event.stopPropagation();cloneCanvas('${c.id}')" title="复制项目">复制</button>
              <button class="ci-action danger" onclick="event.stopPropagation();deleteCanvas('${c.id}','${c.name}')" title="删除项目">✕</button>
            </div>
          </div>`;
        }).join('');
      }
      document.getElementById('canvas-modal').style.display = 'flex';
      renderProjectDrawerList(d.canvases);
    }

    // ═══════════════════════════════════════════════════════════════
    // 左侧项目抽屉
    // ═══════════════════════════════════════════════════════════════
    function toggleProjectDrawer() {
      const drawer = document.getElementById('project-drawer');
      if (drawer.classList.contains('open')) closeProjectDrawer();
      else openProjectDrawer();
    }
    async function openProjectDrawer() {
      document.getElementById('project-drawer').classList.add('open');
      document.getElementById('project-drawer-overlay').classList.add('open');
      await refreshProjectDrawer();
    }
    function closeProjectDrawer() {
      document.getElementById('project-drawer').classList.remove('open');
      document.getElementById('project-drawer-overlay').classList.remove('open');
    }
    async function refreshProjectDrawer() {
      try {
        const r = await _apiFetch('/api/canvas/list');
        const d = await r.json();
        renderProjectDrawerList(d.canvases);
      } catch (e) {
        document.getElementById('project-drawer-body').innerHTML =
          `<div style="color:#5a6573;font-size:12px;text-align:center;padding:20px">加载失败</div>`;
      }
    }
    function renderProjectDrawerList(canvases) {
      const body = document.getElementById('project-drawer-body');
      if (!canvases || canvases.length === 0) {
        body.innerHTML = `<div style="color:#5a6573;font-size:12px;text-align:center;padding:20px">暂无项目<br><span style="font-size:11px">点击上方「新建项目」开始</span></div>`;
        return;
      }
      body.innerHTML = canvases.map(c => {
        const dt = new Date(c.saved_at * 1000).toLocaleDateString('zh-CN');
        const isActive = activeCanvasId === c.id;
        return `<div class="pd-item ${isActive ? 'active' : ''}" onclick="loadCanvas('${c.id}')">
          <div class="pd-icon"><svg><use href="#icon-list"/></svg></div>
          <div class="pd-info">
            <div class="pd-name" title="${c.name}">${c.name}</div>
            <div class="pd-meta">${c.node_count} 节点 · ${dt}</div>
          </div>
          <div class="pd-actions" onclick="event.stopPropagation()">
            <button title="复制" onclick="cloneCanvas('${c.id}')">复制</button>
            <button class="danger" title="删除" onclick="deleteCanvas('${c.id}','${c.name}')">✕</button>
          </div>
        </div>`;
      }).join('');
    }
    async function newProjectFromDrawer() {
      if (!confirm('新建项目会清空当前画布，是否继续？')) return;
      await newProject();
      await refreshProjectDrawer();
    }

    async function loadCanvas(id) {
      const r = await _apiFetch(`/api/canvas/${id}`);
      const d = await r.json();
      activeCanvasId = id;  // 记住画布定义 ID，运行时传给后端
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
      closeProjectDrawer();
      autoSave();
      refreshProjectDrawer();
    }

    function closeModal() { document.getElementById('canvas-modal').style.display = 'none'; }

    async function deleteCanvas(id, name) {
      if (!confirm(`确定删除画布 "${name}"？`)) return;
      try {
        await _apiFetch(`/api/canvas/${id}`, { method: 'DELETE' });
        loadCanvasList(); // 刷新列表
        refreshProjectDrawer();
        if (activeCanvasId === id) {
          activeCanvasId = null;
          currentCanvasId = null;
        }
      } catch (e) {
        alert('删除失败：' + e.message);
      }
    }
    window.newProject = newProject;
    window.cloneCanvas = cloneCanvas;
    window.toggleProjectDrawer = toggleProjectDrawer;
    window.closeProjectDrawer = closeProjectDrawer;
    window.newProjectFromDrawer = newProjectFromDrawer;
    window.refreshProjectDrawer = refreshProjectDrawer;

    // ═══════════════════════════════════════════════════════════════
    // 状态栏
    // ═══════════════════════════════════════════════════════════════

// ─── 命名空间挂载：把本模块声明式函数挂到 TuanboApp.project 做索引 ───
Object.assign(TuanboApp.project, {
  loadCanvasList: loadCanvasList,
  toggleProjectDrawer: toggleProjectDrawer,
  openProjectDrawer: openProjectDrawer,
  closeProjectDrawer: closeProjectDrawer,
  refreshProjectDrawer: refreshProjectDrawer,
  renderProjectDrawerList: renderProjectDrawerList,
  newProjectFromDrawer: newProjectFromDrawer,
  loadCanvas: loadCanvas,
  closeModal: closeModal,
  deleteCanvas: deleteCanvas,
});
