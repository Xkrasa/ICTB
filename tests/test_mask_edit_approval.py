"""自动化回归：mask_edit 执行 + 批准模式闭环（无需真实 AI API）。

测试策略：
1. mask_edit auto_face / auto_full 使用真实执行器（依赖 OpenCV 人脸检测，不联网）。
2. 批准模式闭环通过 monkeypatch 替换 gpt_image / seedance_video executor，避免真实 AI 调用。
"""
import asyncio
import io
import os
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

# 确保从项目根目录导入
os.chdir(Path(__file__).parent.parent)

import orchestrator
from orchestrator.registry import registry
from executors import NODE_EXECUTORS
from storage import storage


def _make_image_bytes(width=512, height=512, with_face=True):
    """生成测试图；with_face=True 时绘制简单人脸，便于 OpenCV 检测。"""
    img = Image.new("RGB", (width, height), (200, 180, 160))
    if with_face:
        draw = ImageDraw.Draw(img)
        face_x, face_y, face_w, face_h = width // 4, height // 6, width // 2, height // 2
        draw.ellipse([face_x, face_y, face_x + face_w, face_y + face_h], fill=(255, 220, 190))
        eye_y = face_y + face_h // 4
        eye_w, eye_h = face_w // 8, face_h // 10
        draw.ellipse([face_x + face_w // 4, eye_y, face_x + face_w // 4 + eye_w, eye_y + eye_h], fill=(50, 50, 50))
        draw.ellipse([face_x + face_w * 3 // 5, eye_y, face_x + face_w * 3 // 5 + eye_w, eye_y + eye_h], fill=(50, 50, 50))
        mouth_x1 = face_x + face_w // 4
        mouth_x2 = face_x + face_w * 3 // 4
        mouth_y = face_y + face_h * 3 // 4
        draw.arc([mouth_x1, mouth_y, mouth_x2, mouth_y + face_h // 12], 0, 180, fill=(200, 100, 100), width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _poll_status(canvas_id: str, node_id: str, timeout: float = 10.0):
    key = f"{canvas_id}:{node_id}"
    start = time.time()
    while time.time() - start < timeout:
        rec = registry.get(key)
        if rec and rec["status"] in ("success", "failed", "blocked", "awaiting_approval"):
            return rec
        await asyncio.sleep(0.1)
    return registry.get(key)


@pytest.fixture
def clean_registry():
    """每个测试前清理相关 canvas 记录（简单实现：备份后恢复）。"""
    keys_before = set(registry._tasks.keys())
    yield
    # 清理本次测试产生的记录
    for k in list(registry._tasks.keys()):
        if k not in keys_before:
            del registry._tasks[k]


@pytest.mark.asyncio
async def test_mask_edit_auto_face(clean_registry):
    canvas_id = "test_mask_auto_face"
    img_bytes = _make_image_bytes()
    img_url = await storage.save(img_bytes, ext="png")

    nodes = [
        {"id": "img", "type": "image_input", "x": 100, "y": 100, "data": {"image_url": img_url}},
        {"id": "mask", "type": "mask_edit", "x": 400, "y": 100, "data": {"mask_mode": "auto_face"}},
    ]
    connections = [
        {"id": "c1", "from": "img", "fromField": "image", "to": "mask", "toField": "image"},
    ]

    statuses = orchestrator.execute_canvas(canvas_id, nodes, connections)
    rec = await _poll_status(canvas_id, "mask", timeout=15.0)
    assert rec is not None, "mask 节点没有记录"
    assert rec["status"] == "success", f"mask_edit 应成功: {rec.get('error')}"
    assert rec.get("mask_url"), "应产出 mask_url"
    assert rec.get("image_url") == img_url, "应透传原图 image_url"


@pytest.mark.asyncio
async def test_mask_edit_auto_full(clean_registry):
    canvas_id = "test_mask_auto_full"
    img_bytes = _make_image_bytes()
    img_url = await storage.save(img_bytes, ext="png")

    nodes = [
        {"id": "img", "type": "image_input", "x": 100, "y": 100, "data": {"image_url": img_url}},
        {"id": "mask", "type": "mask_edit", "x": 400, "y": 100, "data": {"mask_mode": "auto_full"}},
    ]
    connections = [
        {"id": "c1", "from": "img", "fromField": "image", "to": "mask", "toField": "image"},
    ]

    orchestrator.execute_canvas(canvas_id, nodes, connections)
    rec = await _poll_status(canvas_id, "mask", timeout=10.0)
    assert rec is not None
    assert rec["status"] == "success"
    assert rec.get("mask_url")


async def _mock_gpt_image(input_obj, on_progress, on_submitted=None):
    """mock gpt_image 执行器：产出占位图。"""
    await asyncio.sleep(0.05)
    on_progress(50)
    img_bytes = _make_image_bytes(width=512, height=512, with_face=False)
    url = await storage.save(img_bytes, ext="png")
    on_progress(100)
    from node_types import NodeOutput
    return NodeOutput(image_url=url)


async def _mock_seedance_video(input_obj, on_progress, on_submitted=None):
    """mock seedance_video 执行器：产出占位视频 URL。"""
    await asyncio.sleep(0.05)
    on_progress(50)
    from node_types import NodeOutput
    return NodeOutput(video_url="/assets/mock_video.mp4")


@pytest.mark.asyncio
async def test_approval_mode_chain(clean_registry, monkeypatch):
    canvas_id = "test_approval_chain"

    monkeypatch.setitem(NODE_EXECUTORS, "gpt_image", _mock_gpt_image)
    monkeypatch.setitem(NODE_EXECUTORS, "seedance_video", _mock_seedance_video)

    img_bytes = _make_image_bytes()
    img_url = await storage.save(img_bytes, ext="png")

    nodes = [
        {"id": "img", "type": "image_input", "x": 100, "y": 100, "data": {"image_url": img_url}},
        {"id": "gpt", "type": "gpt_image", "x": 400, "y": 100, "data": {"prompt": "mock", "model": "gpt-image-2"}},
        {"id": "vid", "type": "seedance_video", "x": 700, "y": 100, "data": {"prompt": "mock video", "channel": "official"}},
    ]
    connections = [
        {"id": "c1", "from": "img", "fromField": "image", "to": "gpt", "toField": "image1"},
        {"id": "c2", "from": "gpt", "fromField": "image", "to": "vid", "toField": "first_frame"},
    ]

    statuses = orchestrator.execute_canvas(canvas_id, nodes, connections, approval_mode=True)

    # gpt 进入 awaiting_approval
    gpt_rec = await _poll_status(canvas_id, "gpt", timeout=10.0)
    assert gpt_rec["status"] == "awaiting_approval", f"gpt 应进入 awaiting_approval: {gpt_rec}"

    # 批准 gpt
    result = orchestrator.approve_node(canvas_id, "gpt")
    assert result["status"] == "success"

    # vid 进入 awaiting_approval
    vid_rec = await _poll_status(canvas_id, "vid", timeout=10.0)
    assert vid_rec["status"] == "awaiting_approval", f"vid 应进入 awaiting_approval: {vid_rec}"

    # 批准 vid
    result = orchestrator.approve_node(canvas_id, "vid")
    assert result["status"] == "success"

    # 最终状态
    gpt_final = registry.get(f"{canvas_id}:gpt")
    vid_final = registry.get(f"{canvas_id}:vid")
    assert gpt_final["status"] == "success"
    assert vid_final["status"] == "success"
    assert vid_final.get("video_url")


@pytest.mark.asyncio
async def test_reject_blocks_downstream(clean_registry, monkeypatch):
    canvas_id = "test_reject_blocks"
    monkeypatch.setitem(NODE_EXECUTORS, "gpt_image", _mock_gpt_image)
    monkeypatch.setitem(NODE_EXECUTORS, "seedance_video", _mock_seedance_video)

    img_bytes = _make_image_bytes()
    img_url = await storage.save(img_bytes, ext="png")

    nodes = [
        {"id": "img", "type": "image_input", "x": 100, "y": 100, "data": {"image_url": img_url}},
        {"id": "gpt", "type": "gpt_image", "x": 400, "y": 100, "data": {"prompt": "mock"}},
        {"id": "vid", "type": "seedance_video", "x": 700, "y": 100, "data": {"prompt": "mock video"}},
    ]
    connections = [
        {"id": "c1", "from": "img", "fromField": "image", "to": "gpt", "toField": "image1"},
        {"id": "c2", "from": "gpt", "fromField": "image", "to": "vid", "toField": "first_frame"},
    ]

    orchestrator.execute_canvas(canvas_id, nodes, connections, approval_mode=True)
    gpt_rec = await _poll_status(canvas_id, "gpt", timeout=10.0)
    assert gpt_rec["status"] == "awaiting_approval"

    orchestrator.reject_node(canvas_id, "gpt")
    await asyncio.sleep(0.3)

    vid_rec = registry.get(f"{canvas_id}:vid")
    assert vid_rec["status"] == "blocked"
    assert "上游节点" in vid_rec.get("error", "") or "用户拒绝" in vid_rec.get("error", "")
