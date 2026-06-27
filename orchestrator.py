"""异步任务编排引擎（Phase 2：DAG 节点画布）。

参考 ComfyUI 的后端设计：
- execute_canvas：解析节点连线构建 DAG，入度为 0 的节点立即启动
- _schedule_cascade：上游节点成功后自动触发下游（级联执行）
- 失败节点阻断下游（标记 blocked）

保留 Phase 1 的 create_task / _run 兼容旧 API。
"""
import asyncio
import struct
import time
import uuid
import zlib
from collections import defaultdict, deque

from clients import gpt_image
from storage import storage

# 并发闸：最多 3 个节点同时执行
SEM = asyncio.Semaphore(3)

# 后台任务引用集合，防止被 GC 回收
_background_tasks: set = set()


# ───────────────────────── TaskRegistry ─────────────────────────

class TaskRegistry:
    """内存任务注册表，方法签名兼容未来 SQLite 实现"""

    def __init__(self) -> None:
        self._tasks: dict = {}

    def get(self, task_id: str) -> dict | None:
        return self._tasks.get(task_id)

    def set(self, task_id: str, record: dict) -> None:
        self._tasks[task_id] = record

    def update(self, task_id: str, **fields) -> dict | None:
        rec = self._tasks.get(task_id)
        if rec is None:
            return None
        rec.update(fields)
        rec["updated_at"] = time.time()
        return rec

    def list_by_workflow(self, workflow_id: str) -> list:
        return [r for r in self._tasks.values() if r["workflow_id"] == workflow_id]


registry = TaskRegistry()


# ───────────────────────── Phase 1 兼容 ─────────────────────────

def _new_record(task_id: str, workflow_id: str, stage: str) -> dict:
    now = time.time()
    return {
        "task_id": task_id,
        "workflow_id": workflow_id,
        "stage": stage,
        "status": "pending",
        "progress": 0,
        "assets": {
            "character_png": None,
            "poster_png": None,
            "video_mp4": None,
        },
        "error": None,
        "created_at": now,
        "updated_at": now,
    }


def create_task(workflow_id: str, stage: str, params: dict) -> str:
    """Phase 1 兼容：注册 pending 任务并启动后台协程"""
    task_id = uuid.uuid4().hex
    registry.set(task_id, _new_record(task_id, workflow_id, stage))
    t = asyncio.create_task(_run(task_id, stage, params))
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)
    return task_id


async def _run(task_id: str, stage: str, params: dict) -> None:
    try:
        async with SEM:
            registry.update(task_id, status="running", progress=0)
            executor = _STAGE_EXECUTORS.get(stage)
            if executor is None:
                raise ValueError(f"未知阶段: {stage}")
            await executor(task_id, params)
        registry.update(task_id, status="success")
    except Exception as e:  # noqa: BLE001
        registry.update(task_id, status="failed", error=str(e))


# ───────────────────────── Phase 1 执行器 ─────────────────────────

async def execute_mock(task_id: str, params: dict) -> None:
    for p in range(0, 101, 10):
        registry.update(task_id, progress=p)
        await asyncio.sleep(0.5)
    url = await storage.save(_placeholder_png(), "png")
    rec = registry.get(task_id)
    if rec is not None:
        assets = dict(rec["assets"])
        assets["character_png"] = url
        registry.update(task_id, assets=assets)


def _placeholder_png() -> bytes:
    raw = b"\x00\xc0"
    compressed = zlib.compress(raw)

    def _chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")


async def execute_character(task_id: str, params: dict) -> None:
    registry.update(task_id, progress=5)
    ref_bytes = await storage.download(params["reference_image_url"])
    registry.update(task_id, progress=15)
    registry.update(task_id, progress=25)
    png_bytes = await gpt_image.generate_character(
        ref_bytes, params["hair"], params["makeup"], params["clothing"]
    )
    url = await storage.save(png_bytes, "png")
    registry.update(task_id, progress=90)
    rec = registry.get(task_id)
    if rec is not None:
        assets = dict(rec["assets"])
        assets["character_png"] = url
        registry.update(task_id, assets=assets)
    registry.update(task_id, progress=100)


_STAGE_EXECUTORS: dict = {
    "mock": execute_mock,
    "character": execute_character,
}


# ═════════════════════════ Phase 2: DAG 画布编排 ═════════════════════════

def _new_node_record(canvas_id: str, node_id: str, node_type: str) -> dict:
    now = time.time()
    return {
        "task_id": None,          # 运行时才创建
        "canvas_id": canvas_id,
        "node_id": node_id,
        "node_type": node_type,
        "status": "idle",         # idle → pending → running → success / failed / blocked
        "progress": 0,
        "image_url": None,        # 节点产出的图片 URL
        "error": None,
        "created_at": now,
        "updated_at": now,
    }


def execute_canvas(canvas_id: str, nodes: list, connections: list) -> dict:
    """解析 DAG 并启动入度为 0 的节点，返回 {node_id: status} 映射。

    级联执行：上游 success → 自动触发下游；上游 failed → 下游标记 blocked。
    """
    node_map = {n["id"]: n for n in nodes}

    # 构建 DAG
    adj: dict[str, list[str]] = defaultdict(list)   # from -> [to...]
    in_degree: dict[str, int] = {nid: 0 for nid in node_map}
    for conn in connections:
        src, dst = conn["from"], conn["to"]
        adj[src].append(dst)
        in_degree[dst] += 1

    # 注册所有节点
    for nid, node in node_map.items():
        registry.set(
            f"{canvas_id}:{nid}",
            _new_node_record(canvas_id, nid, node.get("type", "unknown")),
        )

    # 存储画布上下文（供级联回调使用）
    _canvas_contexts[canvas_id] = {
        "node_map": node_map,
        "adj": adj,
        "in_degree": in_degree,
        "remaining": dict(in_degree),
    }

    # 启动入度为 0 的节点
    for nid in node_map:
        if in_degree[nid] == 0:
            _start_node(canvas_id, nid)

    return {nid: registry.get(f"{canvas_id}:{nid}")["status"] for nid in node_map}


_canvas_contexts: dict = {}  # canvas_id -> {node_map, adj, in_degree, remaining}


def _start_node(canvas_id: str, node_id: str) -> None:
    """创建 task 并启动节点执行"""
    ctx = _canvas_contexts.get(canvas_id)
    if ctx is None:
        return
    node = ctx["node_map"].get(node_id)
    if node is None:
        return

    task_id = uuid.uuid4().hex
    rec = registry.get(f"{canvas_id}:{node_id}")
    if rec is None:
        return
    rec["task_id"] = task_id
    rec["status"] = "pending"
    rec["progress"] = 0
    rec["error"] = None

    # 合并节点 data 和上游注入的参数
    params = dict(node.get("data", {}))

    t = asyncio.create_task(_run_node(canvas_id, node_id, task_id, node.get("type"), params))
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)


async def _run_node(canvas_id: str, node_id: str, task_id: str,
                    node_type: str, params: dict) -> None:
    """共享并发闸执行节点；成功后级联触发下游"""
    try:
        async with SEM:
            registry.update(f"{canvas_id}:{node_id}", status="running", progress=0)
            executor = _NODE_EXECUTORS.get(node_type)
            if executor is None:
                raise ValueError(f"未知节点类型: {node_type}")
            await executor(canvas_id, node_id, params)
        registry.update(f"{canvas_id}:{node_id}", status="success", progress=100)
        _schedule_cascade(canvas_id, node_id, success=True)
    except Exception as e:  # noqa: BLE001
        registry.update(f"{canvas_id}:{node_id}", status="failed", error=str(e))
        _schedule_cascade(canvas_id, node_id, success=False)


def _schedule_cascade(canvas_id: str, node_id: str, success: bool) -> None:
    """上游完成后：成功→减少下游入度并触发入度为 0 的；失败→下游标记 blocked"""
    ctx = _canvas_contexts.get(canvas_id)
    if ctx is None:
        return

    for downstream in ctx["adj"].get(node_id, []):
        if not success:
            # 上游失败，下游标记 blocked
            rec = registry.get(f"{canvas_id}:{downstream}")
            if rec is not None and rec["status"] == "idle":
                rec["status"] = "blocked"
                rec["error"] = f"上游节点 {node_id} 失败，已阻断"
                # 递归阻断更下游
                _schedule_cascade(canvas_id, downstream, success=False)
            continue

        # 上游成功：把上游产出注入下游参数
        upstream_rec = registry.get(f"{canvas_id}:{node_id}")
        if upstream_rec is not None and upstream_rec.get("image_url"):
            downstream_node = ctx["node_map"].get(downstream, {})
            downstream_data = downstream_node.get("data", {})
            # 如果下游没有自己指定 image_url，就自动注入上游产出
            if not downstream_data.get("image_url"):
                downstream_data["image_url"] = upstream_rec["image_url"]
                downstream_node["data"] = downstream_data

        ctx["remaining"][downstream] -= 1
        if ctx["remaining"][downstream] == 0:
            _start_node(canvas_id, downstream)


# ───────────────────────── 节点执行器 ─────────────────────────

async def exec_image_input(canvas_id: str, node_id: str, params: dict) -> None:
    """图片输入节点：直接把上传的 image_url 作为产出，立即完成"""
    url = params.get("image_url")
    if not url:
        raise ValueError("image_input 节点未上传图片")
    registry.update(f"{canvas_id}:{node_id}", progress=50, image_url=url)
    await asyncio.sleep(0.1)  # 让 UI 有时间渲染
    registry.update(f"{canvas_id}:{node_id}", progress=100)


async def exec_gpt_image(canvas_id: str, node_id: str, params: dict) -> None:
    """AI 生图节点：参考图 + prompt → 背透 PNG"""
    ref_url = params.get("image_url")
    if not ref_url:
        raise ValueError("gpt_image 节点缺少输入图片（请连线 image_input 或上游节点）")
    prompt = params.get("prompt", "")
    hair = params.get("hair")
    makeup = params.get("makeup", "")
    clothing = params.get("clothing", "")

    registry.update(f"{canvas_id}:{node_id}", progress=5)
    ref_bytes = await storage.download(ref_url)
    registry.update(f"{canvas_id}:{node_id}", progress=15)
    registry.update(f"{canvas_id}:{node_id}", progress=25)

    # 有换装参数走 generate_character，否则走自由 prompt
    if hair is not None or makeup or clothing:
        png_bytes = await gpt_image.generate_character(
            ref_bytes, hair or prompt, makeup, clothing
        )
    else:
        png_bytes = await gpt_image.edit_image(
            ref_bytes, prompt or "保持人物特征，优化画面质量"
        )

    url = await storage.save(png_bytes, "png")
    registry.update(f"{canvas_id}:{node_id}", progress=90, image_url=url)


async def exec_remove_bg(canvas_id: str, node_id: str, params: dict) -> None:
    """抠图节点（mock）：直接透传图片。后续接 rembg 真实抠图。"""
    ref_url = params.get("image_url")
    if not ref_url:
        raise ValueError("remove_bg 节点缺少输入图片")
    registry.update(f"{canvas_id}:{node_id}", progress=30)
    # mock：模拟处理耗时
    await asyncio.sleep(1)
    registry.update(f"{canvas_id}:{node_id}", progress=80, image_url=ref_url)
    await asyncio.sleep(0.2)
    registry.update(f"{canvas_id}:{node_id}", progress=100)


async def exec_seedance_video(canvas_id: str, node_id: str, params: dict) -> None:
    """视频生成节点（mock占位）：后续接 seedance API"""
    ref_url = params.get("image_url")
    if not ref_url:
        raise ValueError("seedance_video 节点缺少输入图片")
    registry.update(f"{canvas_id}:{node_id}", progress=10)
    # mock：模拟视频生成耗时
    for p in range(20, 101, 20):
        await asyncio.sleep(0.8)
        registry.update(f"{canvas_id}:{node_id}", progress=p)
    # mock 产出：复用输入图作为"视频封面"
    registry.update(f"{canvas_id}:{node_id}", image_url=ref_url)


_NODE_EXECUTORS: dict = {
    "image_input": exec_image_input,
    "gpt_image": exec_gpt_image,
    "remove_bg": exec_remove_bg,
    "seedance_video": exec_seedance_video,
}
