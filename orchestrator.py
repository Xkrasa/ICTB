"""异步任务编排引擎（Phase 2：DAG 节点画布）。

参考 ComfyUI 的后端设计：
- execute_canvas：解析节点连线构建 DAG，入度为 0 的节点立即启动
- _schedule_cascade：上游节点成功后自动触发下游（级联执行）
- 失败节点阻断下游（标记 blocked）

保留 Phase 1 的 create_task / _run 兼容旧 API。
"""
import asyncio
import json
import logging
import struct
import time
import uuid
import zlib
from collections import defaultdict, deque
from pathlib import Path

import httpx

import config
from clients import gpt_image, rh_image, runninghub
from storage import storage

logger = logging.getLogger("orchestrator")

# 并发闸：最多 3 个节点同时执行
SEM = asyncio.Semaphore(3)

# 后台任务引用集合，防止被 GC 回收
_background_tasks: set = set()


# ───────────────────────── TaskRegistry ─────────────────────────

RUNTIME_DIR = Path("runtime")
RUNTIME_TASKS_DIR = RUNTIME_DIR / "tasks"


def _task_key_to_filename(key: str) -> str:
    """将 registry key（含冒号）转为安全文件名。"""
    return key.replace(":", "__") + ".json"


class TaskRegistry:
    """任务注册表，带 JSON 快照持久化。

    - set/update 时根据变更类型决定是否写盘：终态必写，进度每 10% 写一次。
    - 启动时从快照恢复：终态节点原样恢复，运行中节点标记为 interrupted。
    """

    # 终态：一旦进入这些状态，必须立即持久化
    _TERMINAL_STATES = {"success", "failed", "blocked", "interrupted"}

    def __init__(self) -> None:
        self._tasks: dict = {}
        self._last_persisted_progress: dict[str, int] = {}  # key → 上次写盘时的 progress
        RUNTIME_TASKS_DIR.mkdir(parents=True, exist_ok=True)
        self._restore_from_disk()

    def _restore_from_disk(self) -> None:
        """从磁盘快照恢复任务状态。"""
        if not RUNTIME_TASKS_DIR.exists():
            return
        for f in RUNTIME_TASKS_DIR.glob("*.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            key = f.stem.replace("__", ":")
            # 运行中/排队节点标记为 interrupted
            if rec.get("status") in ("pending", "running"):
                rec["status"] = "interrupted"
                rec["error"] = "服务重启，任务已中断，请重试"
            self._tasks[key] = rec
            self._last_persisted_progress[key] = rec.get("progress", 0)

    def _persist(self, key: str, rec: dict) -> None:
        """将单条记录写入磁盘快照。"""
        try:
            fpath = RUNTIME_TASKS_DIR / _task_key_to_filename(key)
            fpath.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            self._last_persisted_progress[key] = rec.get("progress", 0)
        except OSError:
            pass  # 持久化失败不影响内存逻辑

    def _should_persist(self, key: str, rec: dict, fields: dict) -> bool:
        """判断是否需要写盘：终态必写，关键字段变更必写，进度每 10% 写一次。"""
        # 终态必写
        if rec.get("status") in self._TERMINAL_STATES:
            return True
        # status 变更必写
        if "status" in fields:
            return True
        # image_url / video_url / mask_url / error 变更必写
        if any(k in fields for k in ("image_url", "video_url", "mask_url", "error")):
            return True
        # 进度每 10% 写一次
        new_progress = rec.get("progress", 0)
        last = self._last_persisted_progress.get(key, 0)
        if new_progress // 10 != last // 10:
            return True
        return False

    def get(self, task_id: str) -> dict | None:
        return self._tasks.get(task_id)

    def set(self, task_id: str, record: dict) -> None:
        self._tasks[task_id] = record
        self._persist(task_id, record)

    def update(self, task_id: str, **fields) -> dict | None:
        rec = self._tasks.get(task_id)
        if rec is None:
            return None
        rec.update(fields)
        rec["updated_at"] = time.time()
        if self._should_persist(task_id, rec, fields):
            self._persist(task_id, rec)
        return rec

    def list_by_workflow(self, workflow_id: str) -> list:
        return [r for r in self._tasks.values() if r["workflow_id"] == workflow_id]

    def find_canvas_image_url(self, canvas_id: str, exclude_node_id: str) -> str | None:
        """在同一个 canvas 中查找可作为上游输入的 image_url。

        优先选 node_type == 'image_input' 且 status == 'success' 的节点，
        其次选任何 status == 'success' 且有 image_url 的节点。
        """
        prefix = f"{canvas_id}:"
        candidates = []
        for key, rec in self._tasks.items():
            if not key.startswith(prefix):
                continue
            nid = key[len(prefix):]
            if nid == exclude_node_id:
                continue
            if rec.get("status") != "success" or not rec.get("image_url"):
                continue
            candidates.append((rec.get("node_type", ""), rec["image_url"]))
        # 优先 image_input
        for ntype, url in candidates:
            if ntype == "image_input":
                return url
        # 其次任意成功节点
        if candidates:
            return candidates[0][1]
        return None


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
    # Phase 1 单任务路径：文字描述拼进 prompt，走 edit_image
    # （画布路径 exec_gpt_image 走 generate_character 图片拼接换装）
    hair = params.get("hair", "")
    makeup = params.get("makeup", "")
    clothing = params.get("clothing", "")
    desc = []
    if hair: desc.append(f"发型={hair}")
    if makeup: desc.append(f"妆容={makeup}")
    if clothing: desc.append(f"服装={clothing}")
    prompt = "保持人物五官与参考图完全一致（必须是同一个人）。\n"
    if desc:
        prompt += "换装要求：" + "，".join(desc) + "。\n"
    prompt += "半身/全身站立姿态，自然光线，质感细腻。纯透明背景。高质量，画面中不要出现任何文字与水印。"
    png_bytes = await gpt_image.edit_image(ref_bytes, prompt)
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
        "video_url": None,        # 节点产出的视频 URL
        "mask_url": None,         # 节点产出的遮罩 URL
        "error": None,
        "external_task_id": None, # RH 等外部任务 ID（预留续跑用）
        "created_at": now,
        "updated_at": now,
    }


def execute_canvas(canvas_id: str, nodes: list, connections: list) -> dict:
    """解析 DAG 并启动入度为 0 的节点，返回 {node_id: status} 映射。

    级联执行：上游 success → 自动触发下游；上游 failed → 下游标记 blocked。
    """
    logger.info("execute_canvas %s nodes=%d", canvas_id, len(nodes))
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
    """创建 task 并启动节点执行。

    如果 _canvas_contexts 中没有该 canvas（如服务重启后丢失），
    但 registry 中有该节点的记录，则直接执行该节点（不做级联）。
    """
    ctx = _canvas_contexts.get(canvas_id)
    if ctx is None:
        # 重启后上下文丢失：如果 registry 有该节点，直接执行（无级联）
        rec = registry.get(f"{canvas_id}:{node_id}")
        if rec is None or rec["status"] in ("success", "failed", "blocked", "interrupted"):
            return
        node_type = rec.get("node_type", "unknown")
        # 通过公开方法查找上游 image_url（优先 image_input 节点）
        upstream_url = registry.find_canvas_image_url(canvas_id, node_id)
        if not upstream_url:
            return  # 无法获取上游产出，放弃
        params = {"image_url": upstream_url}
        task_id = uuid.uuid4().hex
        rec["task_id"] = task_id
        rec["status"] = "pending"
        rec["progress"] = 0
        rec["error"] = None
        t = asyncio.create_task(_run_node(canvas_id, node_id, task_id, node_type, params))
        _background_tasks.add(t)
        t.add_done_callback(_background_tasks.discard)
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
        logger.info("node %s:%s success", canvas_id, node_id)
        _schedule_cascade(canvas_id, node_id, success=True)
    except Exception as e:  # noqa: BLE001
        registry.update(f"{canvas_id}:{node_id}", status="failed", error=str(e))
        logger.error("node %s:%s failed: %s", canvas_id, node_id, e)
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
        if upstream_rec is not None:
            downstream_node = ctx["node_map"].get(downstream, {})
            downstream_data = downstream_node.get("data", {})
            changed = False
            # 注入图片
            if upstream_rec.get("image_url") and not downstream_data.get("image_url"):
                downstream_data["image_url"] = upstream_rec["image_url"]
                changed = True
            # 注入视频
            if upstream_rec.get("video_url") and not downstream_data.get("video_url"):
                downstream_data["video_url"] = upstream_rec["video_url"]
                changed = True
            # 注入遮罩
            if upstream_rec.get("mask_url"):
                downstream_data["mask_url"] = upstream_rec["mask_url"]
                changed = True
            if changed:
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
    """AI 生图节点：参考图 + prompt → PNG。

    根据 params.model 分发到不同渠道：
    - gpt-image-2: 原同步渠道，支持 mask 局部重绘与 hair/clothing 换装。
    - rh_gpt_image_i2i / nano_banana_pro / nano_banana_2: RH 工作流异步渠道。
    """
    model = params.get("model", "gpt-image-2")
    logger.info("exec_gpt_image model=%s", model)
    ref_url = params.get("image_url")
    if not ref_url:
        raise ValueError("gpt_image 节点缺少输入图片（请连线 image_input 或上游节点）")

    prompt = params.get("prompt", "")
    aspect_ratio = params.get("aspect_ratio", "16:9")
    resolution = params.get("resolution", "1024x1024")

    registry.update(f"{canvas_id}:{node_id}", progress=5)

    if model == "gpt-image-2":
        await _exec_gpt_image_sync(canvas_id, node_id, params, ref_url)
        return

    # 以下走 RH 工作流异步渠道
    if len(prompt) < 5:
        prompt = "基于参考图生成高质量图像，保持人物特征。"

    ref_bytes = await storage.download(ref_url)
    registry.update(f"{canvas_id}:{node_id}", progress=10)

    if model == "rh_gpt_image_i2i":
        img2_bytes = None
        if params.get("image2_url"):
            img2_bytes = await storage.download(params["image2_url"])
        png_bytes = await rh_image.rh_gpt_image_i2i(
            ref_bytes, img2_bytes, prompt, aspect_ratio, resolution,
            on_progress=_rh_progress_cb(canvas_id, node_id),
            on_submitted=lambda tid: registry.update(
                f"{canvas_id}:{node_id}", external_task_id=tid
            ),
        )
    elif model == "nano_banana_pro":
        png_bytes = await rh_image.nano_banana_pro(
            ref_bytes, prompt, aspect_ratio, resolution,
            on_progress=_rh_progress_cb(canvas_id, node_id),
            on_submitted=lambda tid: registry.update(
                f"{canvas_id}:{node_id}", external_task_id=tid
            ),
        )
    elif model == "nano_banana_2":
        extra_urls = [
            params.get("image2_url"),
            params.get("image3_url"),
            params.get("image4_url"),
            params.get("hair_url"),
            params.get("clothing_url"),
        ]
        extra_urls = [u for u in extra_urls if u]
        images = [ref_bytes]
        for u in extra_urls[:3]:
            images.append(await storage.download(u))
        png_bytes = await rh_image.nano_banana_2(
            images, prompt, aspect_ratio, resolution,
            on_progress=_rh_progress_cb(canvas_id, node_id),
            on_submitted=lambda tid: registry.update(
                f"{canvas_id}:{node_id}", external_task_id=tid
            ),
        )
    else:
        raise ValueError(f"gpt_image 节点未知模型: {model}")

    url = await storage.save(png_bytes, "png")
    registry.update(f"{canvas_id}:{node_id}", progress=95, image_url=url)


async def _exec_gpt_image_sync(
    canvas_id: str, node_id: str, params: dict, ref_url: str
) -> None:
    """gpt-image-2 同步渠道执行逻辑（mask / hair / clothing / edit）。"""
    prompt = params.get("prompt", "")
    hair_url = params.get("hair_url")
    makeup = params.get("makeup", "")
    clothing_url = params.get("clothing_url")
    mask_url = params.get("mask_url")
    size = params.get("size") or params.get("resolution") or config.GPT_IMAGE_SIZE

    registry.update(f"{canvas_id}:{node_id}", progress=15)
    ref_bytes = await storage.download(ref_url)

    # 下载遮罩（如果有）
    mask_bytes = None
    if mask_url:
        registry.update(f"{canvas_id}:{node_id}", progress=20)
        mask_bytes = await storage.download(mask_url)

    registry.update(f"{canvas_id}:{node_id}", progress=25)

    # 有 mask 走局部重绘
    if mask_bytes:
        png_bytes = await gpt_image.edit_image(
            ref_bytes,
            prompt or "在遮罩区域重新生成，保持自然过渡",
            mask_bytes=mask_bytes,
            size=size,
        )
    elif hair_url or clothing_url:
        # 图片换装：下载发型/服装参考图，拼接走 generate_character
        hair_bytes = await storage.download(hair_url) if hair_url else None
        clothing_bytes = await storage.download(clothing_url) if clothing_url else None
        registry.update(f"{canvas_id}:{node_id}", progress=35)
        png_bytes = await gpt_image.generate_character(
            ref_bytes, hair_bytes, makeup, clothing_bytes, size=size
        )
    else:
        png_bytes = await gpt_image.edit_image(
            ref_bytes,
            prompt or "保持人物特征，优化画面质量",
            size=size,
        )

    url = await storage.save(png_bytes, "png")
    registry.update(f"{canvas_id}:{node_id}", progress=90, image_url=url)


async def exec_remove_bg(canvas_id: str, node_id: str, params: dict) -> None:
    """抠图节点：通过 RunningHub AI App 生成透明背景 PNG。"""
    if not config.RUNNINGHUB_API_KEY:
        raise ValueError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")

    ref_url = params.get("image_url")
    if not ref_url:
        raise ValueError("remove_bg 节点缺少输入图片")

    registry.update(f"{canvas_id}:{node_id}", progress=5)

    # 下载输入图片
    ref_bytes = await storage.download(ref_url)
    registry.update(f"{canvas_id}:{node_id}", progress=15)

    # 上传到 RunningHub
    img_url = await runninghub.upload_image(ref_bytes, "remove_bg.png")
    registry.update(f"{canvas_id}:{node_id}", progress=25)

    # 提交 AI App 抠图工作流
    workflow_id = config.RH_REMOVE_BG_WORKFLOW_ID
    nodes = [
        {"nodeId": "3", "fieldName": "image", "fieldValue": img_url, "description": "上传图片"},
    ]
    payload = {
        "nodeInfoList": nodes,
        "instanceType": "default",
        "usePersonalQueue": "false",
    }
    async with httpx.AsyncClient(timeout=config.RUNNINGHUB_TIMEOUT) as client:
        resp = await client.post(
            f"{config.RUNNINGHUB_BASE_URL}/run/ai-app/{workflow_id}",
            headers={
                "Authorization": f"Bearer {config.RUNNINGHUB_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errorCode"):
            raise RuntimeError(
                f"RH 抠图提交失败: {data.get('errorCode')} {data.get('errorMessage', '')}"
            )
        rh_task_id = data["taskId"]

    registry.update(f"{canvas_id}:{node_id}", progress=35, external_task_id=rh_task_id)

    # 轮询任务状态
    elapsed = 0.0
    while elapsed < config.RH_REMOVE_BG_POLL_TIMEOUT:
        result = await runninghub.query_task(rh_task_id)
        status = result.get("status", "")

        if status == "SUCCESS":
            results = result.get("results") or []
            for r in results:
                url = r.get("url")
                if url:
                    async with httpx.AsyncClient(timeout=120) as c:
                        dl = await c.get(url)
                        dl.raise_for_status()
                        png_bytes = dl.content
                    out_url = await storage.save(png_bytes, "png")
                    registry.update(f"{canvas_id}:{node_id}", progress=95, image_url=out_url)
                    return
            raise RuntimeError(f"RH 抠图成功但无图片结果: {result}")

        if status == "FAILED":
            raise RuntimeError(
                f"RH 抠图失败: {result.get('errorMessage', '')} "
                f"errorCode={result.get('errorCode', '')}"
            )

        # 更新进度
        progress = min(35 + int(elapsed / config.RH_REMOVE_BG_POLL_TIMEOUT * 55), 90)
        registry.update(f"{canvas_id}:{node_id}", progress=progress)

        await asyncio.sleep(config.RH_REMOVE_BG_POLL_INTERVAL)
        elapsed += config.RH_REMOVE_BG_POLL_INTERVAL

    raise RuntimeError(
        f"RH 抠图超时（{config.RH_REMOVE_BG_POLL_TIMEOUT}s），task_id={rh_task_id}"
    )


async def exec_seedance_video(canvas_id: str, node_id: str, params: dict) -> None:
    """视频生成节点：RunningHub seedance 图生视频。

    流程：下载本地图片 → 上传到 RunningHub → 提交图生视频 → 轮询 → 下载转存。
    """
    if not config.RUNNINGHUB_API_KEY:
        raise ValueError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")

    ref_url = params.get("image_url")
    if not ref_url:
        raise ValueError("seedance_video 节点缺少输入图片")
    prompt = params.get("prompt", "")
    if len(prompt) < 5:
        prompt = "基于原图生成10秒动态视频，人物自然微笑，缓慢转头。"
    duration = params.get("duration", "8")
    aspect_ratio = params.get("aspect_ratio", "9:16")

    # 1. 下载本地图片
    registry.update(f"{canvas_id}:{node_id}", progress=5)
    ref_bytes = await storage.download(ref_url)

    # 2. 上传到 RunningHub（获取可访问的 URL）
    registry.update(f"{canvas_id}:{node_id}", progress=10)
    rh_image_url = await runninghub.upload_image(ref_bytes)

    # 3. 提交图生视频任务
    registry.update(f"{canvas_id}:{node_id}", progress=15)
    task_id = await runninghub.image_to_video(
        rh_image_url, prompt, duration, aspect_ratio
    )

    # 4. 轮询任务状态（带进度回调）
    def on_progress(status: str) -> None:
        # QUEUED → 20%, RUNNING → 30-80%
        if status == "QUEUED":
            registry.update(f"{canvas_id}:{node_id}", progress=20)
        elif status == "RUNNING":
            cur = registry.get(f"{canvas_id}:{node_id}")
            p = cur["progress"] if cur else 20
            registry.update(f"{canvas_id}:{node_id}", progress=min(p + 5, 80))

    registry.update(f"{canvas_id}:{node_id}", progress=20)
    video_url = await runninghub.wait_for_result(task_id, on_progress)

    # 5. 下载视频并转存（RunningHub URL 24h 过期）
    registry.update(f"{canvas_id}:{node_id}", progress=85)
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(video_url)
        resp.raise_for_status()
        video_bytes = resp.content

    url = await storage.save(video_bytes, "mp4")
    registry.update(f"{canvas_id}:{node_id}", progress=95, video_url=url)


async def exec_mask_edit(canvas_id: str, node_id: str, params: dict) -> None:
    """遮罩编辑节点：透传原图 + 注入 mask_url。

    前端 Canvas 涂抹后上传 mask 到 /api/assets/upload，mask_url 存入 data。
    此节点把 image_url 和 mask_url 同时设入 registry，供下游 gpt_image 使用。
    """
    ref_url = params.get("image_url")
    mask_url = params.get("mask_url")
    if not ref_url:
        raise ValueError("mask_edit 节点缺少输入图片")
    if not mask_url:
        raise ValueError("mask_edit 节点未绘制遮罩（请双击节点编辑遮罩）")
    registry.update(f"{canvas_id}:{node_id}", progress=50, image_url=ref_url, mask_url=mask_url)
    await asyncio.sleep(0.1)
    registry.update(f"{canvas_id}:{node_id}", progress=100)


# ───────────────────────── RH 工作流生图节点 ─────────────────────────

def _rh_progress_cb(canvas_id: str, node_id: str):
    """构造 RH 工作流进度回调：QUEUED→10%, RUNNING→20-80% 渐进。"""
    def cb(status: str) -> None:
        if status == "QUEUED":
            registry.update(f"{canvas_id}:{node_id}", progress=15)
        elif status == "RUNNING":
            cur = registry.get(f"{canvas_id}:{node_id}")
            p = cur["progress"] if cur else 20
            registry.update(f"{canvas_id}:{node_id}", progress=min(p + 5, 80))
    return cb


_NODE_EXECUTORS: dict = {
    "image_input": exec_image_input,
    "mask_edit": exec_mask_edit,
    "gpt_image": exec_gpt_image,
    "remove_bg": exec_remove_bg,
    "seedance_video": exec_seedance_video,
}


# ═════════════════════════ Phase 4: 批量编排 ═════════════════════════

BATCH_DIR = Path("batches")
BATCH_DIR.mkdir(exist_ok=True)

# 候选生成节点类型集合（含历史独立 RH/Nano 类型）
CANDIDATE_IMAGE_NODE_TYPES = {
    "gpt_image",
    "rh_gpt_image_i2i",
    "nano_banana_pro",
    "nano_banana_2",
}

# 历史 RH/Nano 独立节点类型 → gpt_image 模型标识
_LEGACY_NODE_TYPE_TO_MODEL = {
    "rh_gpt_image_i2i": "rh_gpt_image_i2i",
    "nano_banana_pro": "nano_banana_pro",
    "nano_banana_2": "nano_banana_2",
}


def _normalize_node(node: dict) -> dict:
    """将历史 RH/Nano 独立节点类型规范化为 gpt_image + data.model。"""
    old_type = node.get("type", "")
    if old_type in _LEGACY_NODE_TYPE_TO_MODEL:
        node = json.loads(json.dumps(node))  # deep copy
        node["type"] = "gpt_image"
        node.setdefault("data", {})["model"] = _LEGACY_NODE_TYPE_TO_MODEL[old_type]
    return node


def _extract_upstream_dag(
    nodes: list[dict], connections: list[dict], target_id: str
) -> tuple[list[dict], list[dict], list[str]]:
    """提取 target_id 的上游 DAG（不含 target 本身）。

    Returns:
        (upstream_nodes, upstream_connections, direct_upstream_ids)
        direct_upstream_ids: 直接连到 target 的上游节点 id 列表
    """
    node_map = {n["id"]: n for n in nodes}
    # 反向邻接：to -> [from]
    rev: dict[str, list[str]] = {}
    for c in connections:
        rev.setdefault(c["to"], []).append(c["from"])

    # BFS 反向遍历
    visited: set[str] = set()
    queue = list(rev.get(target_id, []))
    direct_upstream_ids = list(queue)
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        for up in rev.get(nid, []):
            if up not in visited:
                queue.append(up)

    upstream_nodes = [json.loads(json.dumps(node_map[nid])) for nid in visited if nid in node_map]
    upstream_connections = [
        json.loads(json.dumps(c))
        for c in connections
        if c["from"] in visited and c["to"] in visited
    ]
    return upstream_nodes, upstream_connections, direct_upstream_ids


async def execute_batch(template: dict, streamers: list, n: int) -> dict:
    """批量编排：每个主播克隆模板候选节点的上游 DAG，复制候选节点 N 份并行。

    支持完整上游 DAG（如 image_input → remove_bg → gpt_image），
    候选节点类型支持 gpt_image 及历史 RH/Nano 独立类型。
    """
    batch_id = "batch_" + uuid.uuid4().hex[:10]
    logger.info("execute_batch batch_id=%s", batch_id)
    items = []

    tpl_nodes = [_normalize_node(nd) for nd in template.get("nodes", [])]
    tpl_conns = template.get("connections", [])

    candidate_nodes = [nd for nd in tpl_nodes if nd.get("type") in CANDIDATE_IMAGE_NODE_TYPES]
    if not candidate_nodes:
        raise ValueError("模板缺少候选生成节点（gpt_image / RH / Nano）")

    # 选择第一个候选生成节点作为模板
    cand_tpl = candidate_nodes[0]
    cand_tpl_id = cand_tpl["id"]
    cand_tpl_data = json.loads(json.dumps(cand_tpl.get("data", {})))

    # 提取候选节点的上游 DAG
    upstream_nodes, upstream_conns, direct_up_ids = _extract_upstream_dag(
        tpl_nodes, tpl_conns, cand_tpl_id
    )

    # 确认上游有 image_input
    image_input_nodes = [nd for nd in upstream_nodes if nd.get("type") == "image_input"]
    if not image_input_nodes:
        raise ValueError("候选链路缺少 image_input 节点")

    for st in streamers:
        streamer_canvas_id = uuid.uuid4().hex
        # 深拷贝上游 DAG，替换 image_input 的图片
        nodes = [json.loads(json.dumps(nd)) for nd in upstream_nodes]
        conns = [json.loads(json.dumps(c)) for c in upstream_conns]

        for nd in nodes:
            if nd.get("type") == "image_input":
                nd.setdefault("data", {})["image_url"] = st["source_image_url"]

        # 复制 N 个候选生成节点，连接到原候选节点的直接上游
        candidate_node_ids = []
        for i in range(n):
            cid = f"cand_{i}"
            candidate_node_ids.append(cid)
            nodes.append({
                "id": cid,
                "type": "gpt_image",
                "x": 400, "y": 100 + i * 80,
                "data": json.loads(json.dumps(cand_tpl_data)),
            })
            for up_id in direct_up_ids:
                conns.append({"id": f"conn_c{i}_{up_id}", "from": up_id, "to": cid})

        execute_canvas(streamer_canvas_id, nodes, conns)

        items.append({
            "streamer_id": st["id"],
            "streamer_name": st.get("name", ""),
            "streamer_avatar": st.get("avatar_url"),
            "phase1_canvas_id": streamer_canvas_id,
            "candidate_node_ids": candidate_node_ids,
            "phase1_nodes": nodes,
            "phase1_connections": conns,
            "candidates": [
                {"node_id": cid, "image_url": None, "status": "idle",
                 "progress": 0, "error": None, "canvas_id": None}
                for cid in candidate_node_ids
            ],
            "adopted_node_id": None,
            "adopted_image_url": None,
            "phase2_canvas_id": None,
            "video_url": None,
            "video_status": None,
            "video_progress": 0,
            "error": None,
        })

    batch = {
        "id": batch_id,
        "template_id": template.get("id"),
        "template_name": template.get("name", ""),
        "candidates_per_streamer": n,
        "status": "running",
        "items": items,
        "created_at": time.time(),
    }
    (BATCH_DIR / f"{batch_id}.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return batch


def _candidate_canvas_id(item: dict, cand: dict) -> str:
    """取候选节点的 canvas_id：优先 cand 级，否则 item 级。"""
    return cand.get("canvas_id") or item["phase1_canvas_id"]


def aggregate_batch(batch_id: str) -> dict:
    """聚合批量任务状态：遍历所有 item 的候选节点，从 registry 读实时状态。"""
    f = BATCH_DIR / f"{batch_id}.json"
    if not f.exists():
        raise FileNotFoundError(f"batch {batch_id} not found")
    batch = json.loads(f.read_text(encoding="utf-8"))
    prev_status = batch.get("status", "")

    all_cands = []
    for item in batch["items"]:
        for cand in item["candidates"]:
            cid = _candidate_canvas_id(item, cand)
            rec = registry.get(f"{cid}:{cand['node_id']}")
            if rec:
                cand["status"] = rec["status"]
                cand["image_url"] = rec.get("image_url")
                cand["progress"] = rec.get("progress", 0)
                cand["error"] = rec.get("error")
            all_cands.append(cand)

        if item.get("phase2_canvas_id"):
            vrec = registry.get(f"{item['phase2_canvas_id']}:video")
            if vrec:
                item["video_status"] = vrec["status"]
                item["video_url"] = vrec.get("video_url")
                item["video_progress"] = vrec.get("progress", 0)

    batch["stats"] = {
        "total": len(all_cands),
        "success": sum(1 for c in all_cands if c["status"] == "success"),
        "running": sum(1 for c in all_cands if c["status"] in ("running", "pending", "idle")),
        "failed": sum(1 for c in all_cands if c["status"] in ("failed", "interrupted")),
    }
    if batch["stats"]["running"] == 0 and batch["status"] == "running":
        batch["status"] = "done"

    # 仅在 batch 状态变化时写盘（防抖：避免每次前端轮询都触发 IO）
    if batch["status"] != prev_status:
        _save_batch(batch)

    return batch


def _save_batch(batch: dict) -> None:
    (BATCH_DIR / f"{batch['id']}.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_batches() -> list[dict]:
    """列出所有历史批次摘要。"""
    result = []
    for f in sorted(BATCH_DIR.glob("batch_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        result.append({
            "id": b["id"],
            "template_name": b.get("template_name", ""),
            "status": b.get("status", ""),
            "created_at": b.get("created_at", 0),
            "streamer_count": len(b.get("items", [])),
            "candidates_per_streamer": b.get("candidates_per_streamer", 0),
        })
    return result


def _load_batch(batch_id: str) -> dict:
    f = BATCH_DIR / f"{batch_id}.json"
    if not f.exists():
        raise FileNotFoundError(f"batch {batch_id} not found")
    return json.loads(f.read_text(encoding="utf-8"))


def adopt_batch(batch_id: str, streamer_id: str, node_id: str) -> dict:
    """候选采用为人工断点：记录 adopted_node_id/adopted_image_url，
    供后续 start_video 二次 canvas run 使用。"""
    batch = _load_batch(batch_id)
    item = next((it for it in batch["items"] if it["streamer_id"] == streamer_id), None)
    if item is None:
        raise ValueError(f"streamer {streamer_id} not in batch")

    cand = next((c for c in item["candidates"] if c["node_id"] == node_id), None)
    if cand is None:
        raise ValueError(f"候选 {node_id} 不存在")
    cid = _candidate_canvas_id(item, cand)
    rec = registry.get(f"{cid}:{node_id}")
    if rec is None or rec["status"] != "success" or not rec.get("image_url"):
        raise ValueError(f"候选 {node_id} 不可采用（未成功或无图）")

    logger.info("adopt overwrite batch=%s streamer=%s old=%s new=%s",
                batch_id, streamer_id, item.get("adopted_node_id"), node_id)

    item["adopted_node_id"] = node_id
    item["adopted_image_url"] = rec["image_url"]
    _save_batch(batch)
    return item


async def retry_candidate(batch_id: str, streamer_id: str, node_id: str) -> dict:
    """重试单个失败/中断候选：只重跑候选节点，复用上游已成功的产出。

    策略：构建最小子图 image_input(上游产出) → 候选节点，
    避免重跑 remove_bg 等已成功的上游预处理。
    """
    logger.info("retry_candidate %s %s", streamer_id, node_id)
    batch = _load_batch(batch_id)
    item = next((it for it in batch["items"] if it["streamer_id"] == streamer_id), None)
    if item is None:
        raise ValueError(f"streamer {streamer_id} not in batch")

    cand = next((c for c in item["candidates"] if c["node_id"] == node_id), None)
    if cand is None:
        raise ValueError(f"候选 {node_id} 不存在")

    if cand["status"] not in ("failed", "interrupted"):
        raise ValueError(f"候选 {node_id} 状态为 {cand['status']}，不允许重试")

    # 尝试从原 phase1 canvas 中获取上游产出
    phase1_canvas = item["phase1_canvas_id"]
    upstream_image_url = None

    # 查找候选节点的直接上游节点
    phase1_conns = item.get("phase1_connections", [])
    direct_upstream = [c["from"] for c in phase1_conns if c["to"] == node_id]

    # 从 registry 获取上游节点的产出图
    for up_id in direct_upstream:
        rec = registry.get(f"{phase1_canvas}:{up_id}")
        if rec and rec.get("image_url"):
            upstream_image_url = rec["image_url"]
            break

    # 如果上游产出不可用（如服务重启丢失），回退到重跑整条 phase1
    if upstream_image_url:
        retry_canvas_id = uuid.uuid4().hex
        nodes = [
            {"id": "img", "type": "image_input", "x": 100, "y": 100,
             "data": {"image_url": upstream_image_url}},
            {"id": node_id, "type": "gpt_image", "x": 400, "y": 100,
             "data": json.loads(json.dumps(
                 next((n.get("data", {}) for n in item["phase1_nodes"]
                       if n.get("id") == node_id), {})
             ))},
        ]
        conns = [{"id": "conn_retry", "from": "img", "to": node_id}]
        execute_canvas(retry_canvas_id, nodes, conns)
    else:
        # 回退：重跑整条 phase1 DAG
        retry_canvas_id = uuid.uuid4().hex
        nodes = json.loads(json.dumps(item["phase1_nodes"]))
        conns = json.loads(json.dumps(item["phase1_connections"]))
        execute_canvas(retry_canvas_id, nodes, conns)

    cand["canvas_id"] = retry_canvas_id
    cand["status"] = "pending"
    cand["progress"] = 0
    cand["image_url"] = None
    cand["error"] = None

    _save_batch(batch)
    return cand


async def start_video(
    batch_id: str, streamer_id: str, prompt: str,
    duration: str = "8", aspect_ratio: str = "9:16",
) -> dict:
    """对已采用主播构造 image_input→seedance_video 单链路 canvas run。

    采用人工断点策略：phase1 候选与 phase2 视频彼此独立，不复用模板链路。
    失败后允许重试：用新 canvas_id 覆盖旧的 phase2_canvas_id。
    """
    batch = _load_batch(batch_id)
    item = next((it for it in batch["items"] if it["streamer_id"] == streamer_id), None)
    if item is None:
        raise ValueError(f"streamer {streamer_id} not in batch")
    if not item.get("adopted_image_url"):
        raise ValueError("尚未采用候选，无法生成视频")
    # 仅在视频进行中或已成功时拒绝；失败后允许重试
    cur_status = item.get("video_status")
    if item.get("phase2_canvas_id") and cur_status in ("pending", "running", "success"):
        raise ValueError("该主播视频已启动或已完成，请勿重复生成")

    phase2_canvas_id = uuid.uuid4().hex
    nodes = [
        {"id": "img", "type": "image_input", "x": 100, "y": 100,
         "data": {"image_url": item["adopted_image_url"]}},
        {"id": "video", "type": "seedance_video", "x": 400, "y": 100,
         "data": {"prompt": prompt, "duration": duration, "aspect_ratio": aspect_ratio}},
    ]
    conns = [{"id": "conn_v", "from": "img", "to": "video"}]
    execute_canvas(phase2_canvas_id, nodes, conns)

    item["phase2_canvas_id"] = phase2_canvas_id
    item["video_status"] = "pending"
    item["video_progress"] = 0
    item["video_url"] = None
    item["error"] = None
    _save_batch(batch)
    return item
