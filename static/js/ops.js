// ═══ 运营生产台（ops.js）═══
// 主播库/模板库/批量生成/候选采用/视频出片
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
          connections: canvasData.connections.map(c => ({ id:c.id, from:c.from, to:c.to, fromField:c.fromField, toField:c.toField }))
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


// ─── 命名空间挂载：把本模块声明式函数挂到 TuanboApp.ops 做索引 ───
Object.assign(TuanboApp.ops, {
  switchMode: switchMode,
  toggleAddStreamerForm: toggleAddStreamerForm,
  previewNewStreamer: previewNewStreamer,
  addStreamer: addStreamer,
  loadStreamers: loadStreamers,
  toggleSelectStreamer: toggleSelectStreamer,
  updateSelectedChips: updateSelectedChips,
  updateTotalCands: updateTotalCands,
  adjustCandidates: adjustCandidates,
  deleteStreamer: deleteStreamer,
  loadTemplates: loadTemplates,
  selectTemplate: selectTemplate,
  saveAsTemplate: saveAsTemplate,
  escapeHtml: escapeHtml,
  loadBatchHistory: loadBatchHistory,
  selectBatchFromHistory: selectBatchFromHistory,
  startBatch: startBatch,
  startBatchPolling: startBatchPolling,
  renderBatch: renderBatch,
  renderVideoPanel: renderVideoPanel,
  startVideo: startVideo,
  retryCandidate: retryCandidate,
  adoptCandidate: adoptCandidate,
});
