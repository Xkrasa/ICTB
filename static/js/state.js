// ═══ 全局状态与常量（state.js）═══
// 全局变量保留 let/const 声明（函数体引用不变）。
    // ═══════════════════════════════════════════════════════════════
    // API Key 访问控制
    // ═══════════════════════════════════════════════════════════════
    const _apiKey = (() => {
      // 优先 URL param → localStorage → prompt
      const fromUrl = new URLSearchParams(location.search).get('api_key');
      if (fromUrl) { localStorage.setItem('api_key', fromUrl); return fromUrl; }
      return localStorage.getItem('api_key') || '';
    })();

    // ═══════════════════════════════════════════════════════════════
    // 数据模型
    // ═══════════════════════════════════════════════════════════════
    let canvasData = { nodes: [], connections: [] };
    let selectedNode = null, selectedConn = null;
    let selectedNodes = new Set();  // Shift+框选/点选的多选集合（区别于单选 selectedNode）
    let currentCanvasId = null;   // 运行实例 ID（后端 /api/canvas/run 返回）
    let activeCanvasId = null;    // 画布定义 ID（loadCanvas 时设置，固定不变）
    const pollTimers = {};
    const nodeElements = {};
    let nodeRuntime = {};  // {nodeId: {status, progress, image_url}} 运行态，不持久化
    let clipboardGraph = null;  // {nodes: [...], connections: [...]} 复制粘贴剪贴板
    let approvalMode = localStorage.getItem('approval_mode') === 'true';  // 批准模式全局开关

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
    // 节点端口定义（与后端 orchestrator.NODE_PORTS 保持一致）
    const NODE_PORTS = {
      image_input: {
        inputs: [],
        outputs: [{ name: 'image', type: 'IMAGE', label: '图片' }]
      },
      gpt_image: {
        inputs: [
          { name: 'image1', type: 'IMAGE', label: '图1 · 主体' },
          { name: 'image2', type: 'IMAGE', label: '图2 · 参考' },
          { name: 'prompt', type: 'TEXT',  label: '提示词' }
        ],
        outputs: [{ name: 'image', type: 'IMAGE', label: '生成图' }]
      },
      remove_bg: {
        inputs: [{ name: 'image', type: 'IMAGE', label: '图片' }],
        outputs: [{ name: 'image', type: 'IMAGE', label: '透明图' }]
      },
      mask_edit: {
        inputs: [{ name: 'image', type: 'IMAGE', label: '待编辑图' }],
        outputs: [
          { name: 'image', type: 'IMAGE', label: '原图' },
          { name: 'mask',  type: 'MASK',  label: '遮罩' }
        ]
      },
      seedance_video: {
        inputs: [
          { name: 'first_frame', type: 'IMAGE', label: '首帧' },
          { name: 'last_frame',  type: 'IMAGE', label: '尾帧（可选）' },
          { name: 'prompt',      type: 'TEXT',  label: '视频描述' }
        ],
        outputs: [{ name: 'video', type: 'VIDEO', label: '视频' }]
      }
    };
    const STATUS_LABELS = { idle:'待机', pending:'排队', running:'运行中', success:'完成', failed:'失败', blocked:'阻断', awaiting_approval:'待批准' };


// ═══ 命名空间容器：各模块函数挂载点 ═══
// 各模块文件末尾用 Object.assign 把声明式函数挂到对应命名空间做索引。
// init.js 加载时再把各命名空间函数平铺到 window（兼容 onclick 的保险层）。
window.TuanboApp = window.TuanboApp || { api: {}, canvas: {}, ops: {}, project: {} };
