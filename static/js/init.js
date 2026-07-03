// ═══ 状态栏 + 自动平铺 + 初始化（init.js）═══
// ─── 自动平铺（保险层）：把各命名空间函数挂到 window，兼容 onclick ───
// 函数本身是声明式（已全局提升），此平铺确保 100% 覆盖 onclick 引用。
(function () {
  var mods = [TuanboApp.api, TuanboApp.canvas, TuanboApp.ops, TuanboApp.project];
  var seen = {};
  mods.forEach(function (mod) {
    if (!mod) return;
    Object.keys(mod).forEach(function (key) {
      if (typeof mod[key] === 'function' && !seen[key]) {
        window[key] = mod[key];
        seen[key] = true;
      }
    });
  });
})();

    function updateStatusbar(state) {
      document.getElementById('sb-nodes').textContent = canvasData.nodes.length;
      document.getElementById('sb-conns').textContent = canvasData.connections.length;
      const dot = document.getElementById('sb-dot'), st = document.getElementById('sb-status');
      dot.className = 'sb-dot';
      if (state === 'running') { dot.classList.add('running'); st.textContent = '运行中...'; }
      else if (state === 'done') { dot.classList.add('success'); st.textContent = '全部完成'; }
      else { st.textContent = '就绪'; }
      // 运行时任务计数
      let running = 0, success = 0, failed = 0;
      for (const nid in nodeRuntime) {
        const r = nodeRuntime[nid];
        if (!r) continue;
        if (r.status === 'running' || r.status === 'pending') running++;
        else if (r.status === 'success') success++;
        else if (r.status === 'failed' || r.status === 'blocked' || r.status === 'interrupted') failed++;
      }
      const $r = document.getElementById('sb-running');
      const $s = document.getElementById('sb-success');
      const $f = document.getElementById('sb-failed');
      const $rd = document.getElementById('sb-dot-running');
      if ($r) $r.textContent = running;
      if ($s) $s.textContent = success;
      if ($f) $f.textContent = failed;
      if ($rd) $rd.style.display = running > 0 ? '' : 'none';
    }

    // ═══════════════════════════════════════════════════════════════
    // 初始化
    // ═══════════════════════════════════════════════════════════════
    applyTransform();
    updateStatusbar();
    updateApprovalButton();

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
