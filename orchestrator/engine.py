"""Phase 2 DAG 画布编排引擎：execute_canvas / 级联 / 批准。"""
import asyncio
import logging
import time
import uuid
from collections import defaultdict

from node_types import NodeOutput
from port_resolver import PortResolver
from executors import NODE_EXECUTORS as _NODE_EXECUTORS
from ._shared import SEM, _background_tasks, classify_error, _record_image_size, logger
from .registry import registry

def _restore_from_node_data(rec: dict, node: dict) -> None:
    """从画布节点的 node.data 恢复历史产物到 registry 记录。

    当 registry 中无旧记录（首次运行/重启丢失）时，用前端 autoSave
    持久化在 node.data 里的产物 URL 恢复，使级联注入能正常工作。
    """
    data = node.get("data", {})
    has_output = False
    for field in ("image_url", "video_url", "mask_url"):
        url = data.get(field)
        if url and not rec.get(field):
            rec[field] = url
            has_output = True
    if has_output:
        rec["status"] = "success"
        rec["progress"] = 100


def _decrement_downstream_remaining(
    canvas_id: str, upstream_id: str, adj: dict
) -> None:
    """非 run_set 的已成功上游：减少下游 remaining 计数。

    原 _inject_upstream_to_downstreams 的入度减少职责。产物注入由
    PortResolver 在执行时从 registry 读取，不再预注入到 node.data。
    """
    ctx = _canvas_contexts.get(canvas_id)
    if ctx is None:
        return
    for downstream in adj.get(upstream_id, []):
        ctx["remaining"][downstream] -= 1


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


def execute_canvas(
    canvas_id: str, nodes: list, connections: list,
    run_node_ids: list | None = None, approval_mode: bool = False
) -> dict:
    """解析 DAG 并启动入度为 0 的节点，返回 {node_id: status} 映射。

    级联执行：上游 success → 自动触发下游；上游 failed → 下游标记 blocked。

    run_node_ids: 本次要运行的节点 ID 列表。
    - 列表内的节点：创建新记录（重置状态），会重新执行。
    - 列表外的节点：保留 registry 旧记录（含历史产物），供级联注入。
    - 为 None 或空：运行全部节点（向后兼容）。

    approval_mode: 是否开启批准模式。开启后 AI 生成节点（gpt_image/seedance_video）
    成功后进入 awaiting_approval 状态，需用户手动批准才继续下游。
    """
    logger.info("execute_canvas %s nodes=%d run_node_ids=%s", canvas_id, len(nodes), run_node_ids)
    node_map = {n["id"]: n for n in nodes}

    # 构建 DAG
    adj: dict[str, list[str]] = defaultdict(list)   # from -> [to...]
    conn_map: dict[tuple[str, str], list[dict]] = defaultdict(list)  # (from, to) -> [conn...]
    in_degree: dict[str, int] = {nid: 0 for nid in node_map}
    for conn in connections:
        src, dst = conn["from"], conn["to"]
        adj[src].append(dst)
        conn_map[(src, dst)].append(conn)
        in_degree[dst] += 1

    # 注册节点：区分「本次运行」与「保留历史」
    run_set = set(run_node_ids) if run_node_ids else set(node_map.keys())
    for nid, node in node_map.items():
        key = f"{canvas_id}:{nid}"
        if nid in run_set:
            # 本次要运行的节点：创建新记录（重置状态，清空产物）
            registry.set(key, _new_node_record(canvas_id, nid, node.get("type", "unknown")))
        else:
            # 不在本次运行集合中的节点：保留旧记录（含历史产物）
            rec = registry.get(key)
            if rec is not None:
                # 旧记录存在：保留产物
                rec["task_id"] = None
                rec["error"] = None
                rec["progress"] = 0
                # 有产物的节点保持 success 状态（供 PortResolver 执行时读取上游产物）
                has_output = rec.get("image_url") or rec.get("video_url") or rec.get("mask_url")
                if has_output:
                    rec["status"] = "success"
                    rec["progress"] = 100
                else:
                    rec["status"] = "idle"
                    # 旧记录无产物：尝试从 node.data 恢复
                    _restore_from_node_data(rec, node)
            else:
                # 旧记录不存在（首次/重启丢失）：从 node.data 恢复产物
                rec = _new_node_record(canvas_id, nid, node.get("type", "unknown"))
                _restore_from_node_data(rec, node)
                registry.set(key, rec)

    # 存储画布上下文（供级联回调使用）
    _canvas_contexts[canvas_id] = {
        "node_map": node_map,
        "adj": adj,
        "conn_map": conn_map,
        "in_degree": in_degree,
        "remaining": dict(in_degree),
        "approval_mode": approval_mode,
    }

    # 对不在 run_set 中的已成功上游：减少下游 remaining
    # （产物注入由 PortResolver 在执行时从 registry 读取，不再预注入 node.data）
    for nid in node_map:
        if nid in run_set:
            continue
        rec = registry.get(f"{canvas_id}:{nid}")
        if rec and rec.get("status") == "success":
            _decrement_downstream_remaining(canvas_id, nid, adj)

    # 启动 run_set 内 remaining 已归零的节点
    for nid in run_set:
        if _canvas_contexts[canvas_id]["remaining"][nid] == 0:
            _start_node(canvas_id, nid)

    return {nid: registry.get(f"{canvas_id}:{nid}")["status"] for nid in node_map}


_canvas_contexts: dict = {}  # canvas_id -> {node_map, adj, in_degree, remaining}


def _gather_upstream(canvas_id: str, node_id: str, ctx) -> tuple[list, list]:
    """从 canvas context 收集本节点的上游 registry 记录 + 连到本节点的连线。"""
    if not ctx or "conn_map" not in ctx:
        return [], []
    conn_map = ctx.get("conn_map", {})
    conns = []
    upstream_ids = set()
    for (frm, to), cl in conn_map.items():
        if to == node_id:
            conns.extend(cl)
            upstream_ids.add(frm)
    upstream_recs = []
    for uid in upstream_ids:
        rec = registry.get(f"{canvas_id}:{uid}")
        if rec:
            upstream_recs.append(rec)
    return upstream_recs, conns


def _start_node(canvas_id: str, node_id: str) -> None:
    """创建 task 并启动节点执行。PortResolver 在 _run_node 内解析上游注入。"""
    ctx = _canvas_contexts.get(canvas_id)
    if ctx is None:
        # 重启后上下文丢失：直接执行（无级联，PortResolver 无上游可注入）
        rec = registry.get(f"{canvas_id}:{node_id}")
        if rec is None or rec["status"] in ("success", "failed", "blocked", "interrupted"):
            return
        node_type = rec.get("node_type", "unknown")
        upstream_url = registry.find_canvas_image_url(canvas_id, node_id)
        if not upstream_url:
            return  # 无法获取上游产出，放弃
        # 构造最小 node（重启兜底：上游产物作为 image_url）
        node = {"id": node_id, "type": node_type, "data": {"image_url": upstream_url}}
        task_id = uuid.uuid4().hex
        rec["task_id"] = task_id
        rec["status"] = "pending"
        rec["progress"] = 0
        rec["error"] = None
        t = asyncio.create_task(_run_node(canvas_id, node_id, task_id, node_type, node, []))
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
    t = asyncio.create_task(_run_node(canvas_id, node_id, task_id, node.get("type"), node, ctx))
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)


async def _run_node(canvas_id: str, node_id: str, task_id: str,
                    node_type: str, node: dict, ctx) -> None:
    """共享并发闸执行节点；PortResolver 解析输入 → 执行器返回产物 → 引擎写 registry。"""
    try:
        async with SEM:
            registry.update(f"{canvas_id}:{node_id}", status="running", progress=0)
            executor = _NODE_EXECUTORS.get(node_type)
            if executor is None:
                raise ValueError(f"未知节点类型: {node_type}")
            # PortResolver：从上游记录 + 连线产出类型化 input
            upstream_recs, conns = _gather_upstream(canvas_id, node_id, ctx)
            input_obj = PortResolver.resolve(node, upstream_recs, conns)
            # 进度回调 + external_task_id 回调（执行器不碰 registry）
            def on_progress(p):
                registry.update(f"{canvas_id}:{node_id}", progress=p)
            def on_submitted(tid):
                registry.update(f"{canvas_id}:{node_id}", external_task_id=tid)
            out: NodeOutput = await executor(input_obj, on_progress, on_submitted)

        # 引擎写产物到 registry
        asset_updates = {}
        if out.image_url: asset_updates["image_url"] = out.image_url
        if out.video_url: asset_updates["video_url"] = out.video_url
        if out.mask_url:  asset_updates["mask_url"] = out.mask_url
        if asset_updates:
            registry.update(f"{canvas_id}:{node_id}", **asset_updates)
        if out.image_url:
            await _record_image_size(canvas_id, node_id, out.image_url)

        # 批准模式：AI 生成节点成功后暂停，等待用户审批
        if isinstance(ctx, dict) and ctx.get("approval_mode") and node_type in ("gpt_image", "seedance_video"):
            registry.update(
                f"{canvas_id}:{node_id}",
                status="awaiting_approval", progress=100, error=None,
            )
            logger.info("node %s:%s awaiting approval", canvas_id, node_id)
            return

        registry.update(f"{canvas_id}:{node_id}", status="success", progress=100)
        logger.info("node %s:%s success", canvas_id, node_id)
        _schedule_cascade(canvas_id, node_id, success=True)
    except Exception as e:  # noqa: BLE001
        err_info = classify_error(str(e))
        registry.update(f"{canvas_id}:{node_id}", status="failed", error=f"[{err_info['code']}] {err_info['label']}: {e}")
        logger.error("node %s:%s failed: %s", canvas_id, node_id, e)
        _schedule_cascade(canvas_id, node_id, success=False)


def approve_node(canvas_id: str, node_id: str) -> dict:
    """批准模式：将通过审核的节点标记为 success 并继续级联下游。"""
    key = f"{canvas_id}:{node_id}"
    rec = registry.get(key)
    if rec is None:
        raise ValueError("节点不存在")
    if rec.get("status") != "awaiting_approval":
        raise ValueError(f"节点状态为 {rec.get('status')}，不是待批准状态")
    registry.update(key, status="success", error=None)
    logger.info("node %s:%s approved", canvas_id, node_id)
    _schedule_cascade(canvas_id, node_id, success=True)
    return {"node_id": node_id, "status": "success"}


def reject_node(canvas_id: str, node_id: str) -> dict:
    """批准模式：拒绝节点产出，标记 failed 并阻断下游。"""
    key = f"{canvas_id}:{node_id}"
    rec = registry.get(key)
    if rec is None:
        raise ValueError("节点不存在")
    if rec.get("status") != "awaiting_approval":
        raise ValueError(f"节点状态为 {rec.get('status')}，不是待批准状态")
    registry.update(key, status="failed", error="用户拒绝该生成结果")
    logger.info("node %s:%s rejected", canvas_id, node_id)
    _schedule_cascade(canvas_id, node_id, success=False)
    return {"node_id": node_id, "status": "failed"}


def _schedule_cascade(canvas_id: str, node_id: str, success: bool) -> None:
    """上游完成后：成功→减少下游入度并触发入度为 0 的；失败→下游标记 blocked。

    产物注入由 PortResolver 在 _run_node 执行时从 registry 读取，这里只管
    入度计数 + 触发（原注入逻辑已删除）。
    """
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

        ctx["remaining"][downstream] -= 1
        if ctx["remaining"][downstream] == 0:
            _start_node(canvas_id, downstream)


# ───────────────────────── 进程重启后续跑 ──────────────────────────

_RESUMEABLE_NODE_TYPES = {"seedance_video"}


def _resume_node(canvas_id: str, node_id: str, rec: dict) -> asyncio.Task:
    """恢复单个已提交外部任务但进程重启丢失的节点执行，返回后台任务。"""
    node_type = rec.get("node_type", "unknown")
    external_task_id = rec.get("external_task_id")
    key = f"{canvas_id}:{node_id}"

    async def _run_resume() -> None:
        try:
            from executors import NODE_EXECUTORS
            executor = NODE_EXECUTORS.get(node_type)
            if executor is None:
                raise ValueError(f"未知节点类型: {node_type}")
            # 执行器必须有 resume 入口
            resume_fn = getattr(executor, "resume", None)
            if resume_fn is None:
                raise ValueError(f"节点 {node_type} 不支持续跑")

            def on_progress(p: int) -> None:
                registry.update(key, progress=p)

            out = await resume_fn(external_task_id, rec.get("channel", ""), on_progress)
            asset_updates = {}
            if out.image_url: asset_updates["image_url"] = out.image_url
            if out.video_url: asset_updates["video_url"] = out.video_url
            if out.mask_url:  asset_updates["mask_url"] = out.mask_url
            if asset_updates:
                registry.update(key, **asset_updates)
            registry.update(key, status="success", progress=100, error=None)
            logger.info("resumed node %s:%s success", canvas_id, node_id)
        except Exception as e:  # noqa: BLE001
            err_info = classify_error(str(e))
            registry.update(key, status="failed", error=f"[{err_info['code']}] {err_info['label']}: {e}")
            logger.error("resumed node %s:%s failed: %s", canvas_id, node_id, e)

    registry.update(key, status="running", error=None)
    loop = asyncio.get_running_loop()
    t = loop.create_task(_run_resume())
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)
    return t


async def resume_interrupted_nodes() -> list[asyncio.Task]:
    """启动时扫描 registry，恢复已提交外部任务但未完成的节点。

    恢复条件：status == running 或 pending，且有 external_task_id。
    返回创建的后台任务列表，调用方（lifespan）可 await gather。
    设计为 async 函数，确保始终在事件循环内创建 task。
    """
    tasks = []
    for key, rec in registry._tasks.items():
        if ":" not in key:
            continue
        canvas_id, node_id = key.split(":", 1)
        status = rec.get("status")
        node_type = rec.get("node_type", "")
        if status not in ("running", "pending"):
            continue
        if node_type not in _RESUMEABLE_NODE_TYPES:
            continue
        if not rec.get("external_task_id"):
            continue
        tasks.append(_resume_node(canvas_id, node_id, rec))
    if tasks:
        logger.info("resumed %d interrupted nodes", len(tasks))
    return tasks
