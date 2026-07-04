// ═══ 素材库（material.js）═══
// 分类：real(真人) / virtual(虚拟) / group(团播)
// 团播子分类：streamer(主播形象) / hair(发型) / clothing(服装) / background(背景)
window.TuanboApp = window.TuanboApp || { api: {}, canvas: {}, ops: {}, project: {} };

const MATERIAL_CATEGORIES = [
  { key: 'real',    label: '真人素材', subtabs: [] },
  { key: 'virtual', label: '虚拟素材', subtabs: [] },
  { key: 'group',   label: '团播素材', subtabs: [
    { key: 'streamer',  label: '主播形象' },
    { key: 'hair',      label: '发型' },
    { key: 'clothing',  label: '服装' },
    { key: 'background',label: '背景' },
  ]},
];

let matCurrentCategory = 'real';
let matCurrentSubcategory = '';

function openMaterialPanel(category) {
  matCurrentCategory = category;
  matCurrentSubcategory = '';
  const panel = document.getElementById('material-panel');
  panel.classList.add('open');
  renderMatTabs();
  renderMatSubtabs();
  loadMaterials();
}

function closeMaterialPanel() {
  document.getElementById('material-panel').classList.remove('open');
}

function renderMatTabs() {
  const el = document.getElementById('mat-tabs');
  el.innerHTML = MATERIAL_CATEGORIES.map(c =>
    `<button class="mat-tab ${c.key === matCurrentCategory ? 'active' : ''}" onclick="switchMatCategory('${c.key}')">${c.label}</button>`
  ).join('');
}

function switchMatCategory(key) {
  matCurrentCategory = key;
  matCurrentSubcategory = '';
  renderMatTabs();
  renderMatSubtabs();
  loadMaterials();
}

function renderMatSubtabs() {
  const el = document.getElementById('mat-subtabs');
  const cat = MATERIAL_CATEGORIES.find(c => c.key === matCurrentCategory);
  if (!cat || cat.subtabs.length === 0) {
    el.innerHTML = '';
    el.style.display = 'none';
    return;
  }
  el.style.display = 'flex';
  el.innerHTML = `<button class="mat-subtab ${!matCurrentSubcategory ? 'active' : ''}" onclick="switchMatSubcategory('')">全部</button>` +
    cat.subtabs.map(s =>
      `<button class="mat-subtab ${s.key === matCurrentSubcategory ? 'active' : ''}" onclick="switchMatSubcategory('${s.key}')">${s.label}</button>`
    ).join('');
}

function switchMatSubcategory(key) {
  matCurrentSubcategory = key;
  renderMatSubtabs();
  loadMaterials();
}

async function loadMaterials() {
  const grid = document.getElementById('mat-grid');
  grid.innerHTML = '<div class="mat-loading">加载中...</div>';
  try {
    const params = new URLSearchParams({ category: matCurrentCategory });
    if (matCurrentSubcategory) params.set('subcategory', matCurrentSubcategory);
    const r = await _apiFetch(`/api/materials?${params}`);
    if (!r.ok) throw new Error('加载失败');
    const d = await r.json();
    renderMatGrid(d.materials || []);
  } catch(e) {
    grid.innerHTML = `<div class="mat-loading">${e.message}</div>`;
  }
}

function renderMatGrid(materials) {
  const grid = document.getElementById('mat-grid');
  if (materials.length === 0) {
    grid.innerHTML = '<div class="mat-loading">暂无素材，点击上方上传</div>';
    return;
  }
  grid.innerHTML = materials.map(m => `
    <div class="mat-item" onclick="addMaterialToCanvas('${m.url}')" title="${m.name}">
      <div class="mat-thumb">
        <img src="${m.url}" loading="lazy"/>
      </div>
      <div class="mat-name">${m.name}</div>
      <button class="mat-del" onclick="event.stopPropagation();deleteMaterial('${m.id}','${m.url}')" title="删除">✕</button>
    </div>
  `).join('');
}

function uploadMaterial() {
  document.getElementById('mat-upload-input').click();
}

async function handleMaterialUpload(input) {
  const file = input.files[0];
  if (!file) return;
  try {
    // 1. 上传文件
    const fd = new FormData();
    fd.append('file', file);
    const r1 = await _apiFetch('/api/assets/upload', { method: 'POST', body: fd });
    if (!r1.ok) throw new Error('上传失败');
    const d1 = await r1.json();
    // 2. 创建素材记录
    const r2 = await _apiFetch('/api/materials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: d1.url,
        category: matCurrentCategory,
        subcategory: matCurrentSubcategory,
        name: file.name.replace(/\.[^.]+$/, ''),
      })
    });
    if (!r2.ok) throw new Error('记录创建失败');
    showToast('素材上传成功');
    loadMaterials();
  } catch(e) {
    showToast('上传失败: ' + e.message, 'error');
  }
  input.value = '';
}

async function deleteMaterial(mid, url) {
  if (!confirm('确认删除该素材？')) return;
  try {
    await _apiFetch(`/api/materials/${mid}`, { method: 'DELETE' });
    loadMaterials();
    showToast('已删除');
  } catch(e) {
    showToast('删除失败', 'error');
  }
}

function addMaterialToCanvas(url) {
  // 添加 image_input 节点并自动设置图片
  const w = window.innerWidth / 2;
  const h = window.innerHeight / 2;
  const cs = screenToCanvas(w, h);
  addNodeAt('image_input', cs.x, cs.y);
  // 设置刚添加节点的图片
  const node = canvasData.nodes[canvasData.nodes.length - 1];
  node.data.image_url = url;
  refreshNodePreview(node.id);
  autoSave();
  closeMaterialPanel();
  showToast('已添加到画布');
}

// 挂载到 window
window.openMaterialPanel = openMaterialPanel;
window.closeMaterialPanel = closeMaterialPanel;
window.switchMatCategory = switchMatCategory;
window.switchMatSubcategory = switchMatSubcategory;
window.uploadMaterial = uploadMaterial;
window.handleMaterialUpload = handleMaterialUpload;
window.deleteMaterial = deleteMaterial;
window.addMaterialToCanvas = addMaterialToCanvas;
