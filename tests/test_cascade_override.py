"""级联注入覆盖逻辑单元测试。

验证 docs/research/优化方案.txt 问题 9.1 的修复：
连线注入 image_url 时，对链路型下游节点（gpt_image / remove_bg /
mask_edit / seedance_video）允许上游新图覆盖旧值；其它节点仅在为空时注入。

不依赖网络 / API key，直接对 orchestrator._schedule_cascade 做白盒测试。

运行：python -m pytest tests/test_cascade_override.py -v --tb=short
"""
import pytest

import orchestrator
from orchestrator import TaskRegistry, _schedule_cascade


# 链路型节点：重新跑上游时应被新图覆盖
OVERRIDABLE_TYPES = ["gpt_image", "remove_bg", "mask_edit", "seedance_video"]
# 非链路型节点：仅在下游为空时注入，不覆盖既有旧图
PASS_THROUGH_TYPES = ["image_input", "unknown_node"]


def _setup_canvas(monkeypatch, canvas_id, downstream_type, downstream_has_old_image):
    """构造一个 canvas：上游 up 已成功（产出 new_url），下游 down 接收注入。

    下游 remaining 设为 2，cascade 一次后变 1，不归零 → 不会触发真实节点执行。
    """
    registry = TaskRegistry()
    monkeypatch.setattr(orchestrator, "registry", registry)

    upstream_node = {"id": "up", "type": "image_input", "data": {}}
    downstream_data = {}
    if downstream_has_old_image:
        downstream_data["image_url"] = "/assets/OLD.png"
    downstream_node = {
        "id": "down",
        "type": downstream_type,
        "data": downstream_data,
    }

    node_map = {"up": upstream_node, "down": downstream_node}
    ctx = {
        "node_map": node_map,
        "adj": {"up": ["down"]},          # up → down
        "remaining": {"down": 2},          # 一次 cascade 后变 1，不触发 _start_node
    }
    monkeypatch.setitem(orchestrator._canvas_contexts, canvas_id, ctx)

    # 上游节点已成功，产出新图
    registry.set(f"{canvas_id}:up", {
        "status": "success",
        "image_url": "/assets/NEW.png",
        "node_type": "image_input",
    })
    registry.set(f"{canvas_id}:down", {"status": "idle", "node_type": downstream_type})

    # _start_node 在 remaining 归零时会真正建 task；这里 remaining 不会归零，
    # 但为稳妥起见把它 stub 掉，确保测试不会意外触发网络执行。
    monkeypatch.setattr(orchestrator, "_start_node", lambda *a, **k: None)

    return downstream_node


@pytest.mark.parametrize("ntype", OVERRIDABLE_TYPES)
def test_overridable_node_old_image_replaced(monkeypatch, ntype):
    """链路型节点：已有旧图时，上游新图应覆盖旧图。"""
    canvas_id = f"test-{ntype}-override"
    downstream = _setup_canvas(monkeypatch, canvas_id, ntype, downstream_has_old_image=True)

    _schedule_cascade(canvas_id, "up", success=True)

    assert downstream["data"]["image_url"] == "/assets/NEW.png", (
        f"{ntype} 应被上游新图覆盖，但仍是 {downstream['data']['image_url']!r}"
    )


@pytest.mark.parametrize("ntype", PASS_THROUGH_TYPES)
def test_pass_through_node_old_image_kept(monkeypatch, ntype):
    """非链路型节点：已有旧图时，不注入（保留旧图）。"""
    canvas_id = f"test-{ntype}-keep"
    downstream = _setup_canvas(monkeypatch, canvas_id, ntype, downstream_has_old_image=True)

    _schedule_cascade(canvas_id, "up", success=True)

    assert downstream["data"]["image_url"] == "/assets/OLD.png", (
        f"{ntype} 不应被覆盖，但已变成 {downstream['data']['image_url']!r}"
    )


@pytest.mark.parametrize("ntype", OVERRIDABLE_TYPES + PASS_THROUGH_TYPES)
def test_empty_image_always_injected(monkeypatch, ntype):
    """所有节点：下游为空时都应注入上游图。"""
    canvas_id = f"test-{ntype}-inject"
    downstream = _setup_canvas(monkeypatch, canvas_id, ntype, downstream_has_old_image=False)

    _schedule_cascade(canvas_id, "up", success=True)

    assert downstream["data"]["image_url"] == "/assets/NEW.png"


def test_upstream_failure_blocks_downstream(monkeypatch):
    """上游失败时：下游标记 blocked，不注入任何字段。"""
    canvas_id = "test-fail-block"
    downstream = _setup_canvas(
        monkeypatch, canvas_id, "seedance_video", downstream_has_old_image=True
    )

    _schedule_cascade(canvas_id, "up", success=False)

    # 不应注入新图（旧图保留）
    assert downstream["data"]["image_url"] == "/assets/OLD.png"
    # 下游 registry 被标记为 blocked
    rec = orchestrator.registry.get(f"{canvas_id}:down")
    assert rec["status"] == "blocked"


def test_video_url_and_mask_url_injection(monkeypatch):
    """上游产出 video_url / mask_url 时，下游为空才注入。"""
    canvas_id = "test-video-mask"
    registry = TaskRegistry()
    monkeypatch.setattr(orchestrator, "registry", registry)

    downstream = {"id": "down", "type": "seedance_video", "data": {}}
    ctx = {
        "node_map": {"up": {"id": "up", "type": "gpt_image", "data": {}}, "down": downstream},
        "adj": {"up": ["down"]},
        "remaining": {"down": 2},
    }
    monkeypatch.setitem(orchestrator._canvas_contexts, canvas_id, ctx)
    monkeypatch.setattr(orchestrator, "_start_node", lambda *a, **k: None)

    registry.set(f"{canvas_id}:up", {
        "status": "success",
        "image_url": "/assets/img.png",
        "video_url": "/assets/v.mp4",
        "mask_url": "/assets/m.png",
        "node_type": "gpt_image",
    })
    registry.set(f"{canvas_id}:down", {"status": "idle", "node_type": "seedance_video"})

    _schedule_cascade(canvas_id, "up", success=True)

    assert downstream["data"]["image_url"] == "/assets/img.png"
    assert downstream["data"]["video_url"] == "/assets/v.mp4"
    assert downstream["data"]["mask_url"] == "/assets/m.png"


# ═══════════════════════════════════════════════════════════════
# 断点续跑测试：验证 execute_canvas + run_node_ids 的交互
# ═══════════════════════════════════════════════════════════════


def _make_chain_nodes():
    """构造 image_input → gpt_image → seedance_video 三节点链路。"""
    return [
        {"id": "img1", "type": "image_input", "x": 0, "y": 0, "data": {}},
        {"id": "gen1", "type": "gpt_image", "x": 200, "y": 0, "data": {"model": "gpt-image-2", "prompt": "test"}},
        {"id": "vid1", "type": "seedance_video", "x": 400, "y": 0, "data": {"prompt": "video"}},
    ]


def _make_chain_conns():
    return [
        {"id": "c1", "from": "img1", "to": "gen1"},
        {"id": "c2", "from": "gen1", "to": "vid1"},
    ]


def test_rerun_downstream_preserves_upstream_output(monkeypatch):
    """重跑下游节点时，不在 run_node_ids 内的上游节点保留历史产物。

    模拟：第一次跑完整链路（img1→gen1→vid1），img1 产出图片。
    第二次只重跑 gen1+vid1，img1 不在 run_node_ids 内。
    预期：img1 的 image_url 保留，gen1 通过级联注入拿到 img1 的图片。
    """
    from orchestrator import execute_canvas

    registry = TaskRegistry()
    monkeypatch.setattr(orchestrator, "registry", registry)
    monkeypatch.setattr(orchestrator, "_start_node", lambda *a, **k: None)

    canvas_id = "test-rerun-1"

    # 第一次运行：完整链路
    nodes = _make_chain_nodes()
    conns = _make_chain_conns()
    execute_canvas(canvas_id, nodes, conns)

    # 模拟 img1 运行成功，产出图片
    registry.update(f"{canvas_id}:img1", status="success", progress=100, image_url="/assets/photo.png")

    # 第二次运行：只重跑 gen1+vid1
    execute_canvas(canvas_id, nodes, conns, run_node_ids=["gen1", "vid1"])

    # img1 的产物应保留
    img1_rec = registry.get(f"{canvas_id}:img1")
    assert img1_rec["image_url"] == "/assets/photo.png", "img1 历史产物不应被覆盖"

    # gen1 应被重置为 idle（在 run_set 内）
    gen1_rec = registry.get(f"{canvas_id}:gen1")
    assert gen1_rec["status"] == "idle", f"gen1 应为 idle，实际是 {gen1_rec['status']}"
    assert gen1_rec.get("image_url") is None, "gen1 产物应被清空（要重新执行）"

    # gen1 的 node.data 应已被注入 img1 的产物（通过 _inject_upstream_to_downstreams）
    gen1_node = next(n for n in nodes if n["id"] == "gen1")
    assert gen1_node["data"].get("image_url") == "/assets/photo.png", (
        f"gen1 node.data.image_url 应被注入 img1 产出，实际是 {gen1_node['data'].get('image_url')!r}"
    )


def test_rerun_single_node_with_upstream_history(monkeypatch):
    """单独重跑下游节点（如 seedance_video），上游 gpt_image 产物保留。

    场景：image_input → gpt_image → seedance_video
    第一次跑完 gpt_image 成功产出 AI 图。第二次只重跑 seedance_video。
    预期：seedance_video 通过级联拿到 gpt_image 的产物。
    """
    from orchestrator import execute_canvas

    registry = TaskRegistry()
    monkeypatch.setattr(orchestrator, "registry", registry)
    monkeypatch.setattr(orchestrator, "_start_node", lambda *a, **k: None)

    canvas_id = "test-rerun-2"

    # 第一次运行：完整链路
    nodes = _make_chain_nodes()
    conns = _make_chain_conns()
    execute_canvas(canvas_id, nodes, conns)

    # 模拟 img1 + gen1 都成功
    registry.update(f"{canvas_id}:img1", status="success", progress=100, image_url="/assets/photo.png")
    registry.update(f"{canvas_id}:gen1", status="success", progress=100, image_url="/assets/ai_art.png")

    # 第二次运行：只重跑 seedance_video
    execute_canvas(canvas_id, nodes, conns, run_node_ids=["vid1"])

    # img1 和 gen1 的产物应保留
    assert registry.get(f"{canvas_id}:img1")["image_url"] == "/assets/photo.png"
    assert registry.get(f"{canvas_id}:gen1")["image_url"] == "/assets/ai_art.png"

    # vid1 的 node.data 应已被注入 gen1 的产物
    vid1_node = next(n for n in nodes if n["id"] == "vid1")
    assert vid1_node["data"].get("image_url") == "/assets/ai_art.png", (
        f"vid1 应被注入 gen1 产出，实际是 {vid1_node['data'].get('image_url')!r}"
    )


def test_rerun_restores_from_node_data_when_registry_missing(monkeypatch):
    """重启后 registry 丢失，从 node.data 恢复产物。"""
    from orchestrator import execute_canvas

    registry = TaskRegistry()
    monkeypatch.setattr(orchestrator, "registry", registry)
    monkeypatch.setattr(orchestrator, "_start_node", lambda *a, **k: None)

    canvas_id = "test-restore-nodedata"

    # 节点数据里已经带着历史产物（前端 autoSave 保存的）
    nodes = [
        {"id": "img1", "type": "image_input", "x": 0, "y": 0,
         "data": {"image_url": "/assets/saved_photo.png"}},
        {"id": "gen1", "type": "gpt_image", "x": 200, "y": 0,
         "data": {"model": "gpt-image-2", "prompt": "test"}},
    ]
    conns = [{"id": "c1", "from": "img1", "to": "gen1"}]

    # 只重跑 gen1（img1 不在 run_node_ids 内，registry 也没有它的记录）
    execute_canvas(canvas_id, nodes, conns, run_node_ids=["gen1"])

    # img1 的 registry 记录应从 node.data 恢复
    img1_rec = registry.get(f"{canvas_id}:img1")
    assert img1_rec is not None, "img1 应有 registry 记录"
    assert img1_rec["image_url"] == "/assets/saved_photo.png", (
        f"img1 应从 node.data 恢复产物，实际是 {img1_rec.get('image_url')!r}"
    )
    assert img1_rec["status"] == "success", "有产物的节点应标记为 success"

    # gen1 的 node.data 应被注入 img1 恢复的产物
    gen1_node = next(n for n in nodes if n["id"] == "gen1")
    assert gen1_node["data"].get("image_url") == "/assets/saved_photo.png"


def test_rerun_injects_video_and_mask_urls(monkeypatch):
    """重跑下游时，video_url 和 mask_url 也能从历史记录注入。"""
    from orchestrator import execute_canvas

    registry = TaskRegistry()
    monkeypatch.setattr(orchestrator, "registry", registry)
    monkeypatch.setattr(orchestrator, "_start_node", lambda *a, **k: None)

    canvas_id = "test-rerun-video-mask"

    nodes = [
        {"id": "gen1", "type": "gpt_image", "x": 0, "y": 0, "data": {}},
        {"id": "vid1", "type": "seedance_video", "x": 200, "y": 0, "data": {}},
    ]
    conns = [{"id": "c1", "from": "gen1", "to": "vid1"}]

    # 第一次运行：gen1 成功产出 image + mask
    execute_canvas(canvas_id, nodes, conns)
    registry.update(f"{canvas_id}:gen1", status="success", progress=100,
                    image_url="/assets/art.png", mask_url="/assets/mask.png")

    # 第二次运行：只重跑 vid1
    execute_canvas(canvas_id, nodes, conns, run_node_ids=["vid1"])

    # vid1 的 node.data 应同时拿到 image_url 和 mask_url
    vid1_node = next(n for n in nodes if n["id"] == "vid1")
    assert vid1_node["data"].get("image_url") == "/assets/art.png"
    assert vid1_node["data"].get("mask_url") == "/assets/mask.png"
