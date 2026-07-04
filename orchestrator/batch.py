"""Phase 4 批量编排：模板克隆 + 候选并行 + 采用 + 视频。"""
import json
import logging
import time
import uuid
from pathlib import Path

from storage import storage
from ._shared import logger
from .registry import registry
from .engine import execute_canvas

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
