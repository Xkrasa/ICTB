"""TaskRegistry SQLite 持久化回归测试。"""
import json
import os
import tempfile
import time

import pytest

from orchestrator.registry import TaskRegistry


@pytest.fixture
def tmp_registry():
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "tasks.db")
        reg = TaskRegistry(db_path=db_path)
        yield reg
        reg.close()


def test_set_persists_and_restores(tmp_registry):
    reg = tmp_registry
    reg.set("c1:n1", {"status": "running", "progress": 25, "image_url": None})

    # 模拟重启：新建实例读取同一 db
    reg2 = TaskRegistry(db_path=reg._db_path)
    try:
        rec = reg2.get("c1:n1")
        assert rec is not None
        assert rec["status"] == "running"
        assert rec["progress"] == 25
    finally:
        reg2.close()


def test_update_progress_throttle(tmp_registry):
    reg = tmp_registry
    reg.set("c1:n1", {"status": "running", "progress": 0})
    for p in range(1, 12):
        reg.update("c1:n1", progress=p)

    # 进度 0->9 不触发写盘，10 触发；11 不触发（同十位数）
    with reg._lock:
        rows = reg._conn.execute("SELECT COUNT(*) FROM task_records").fetchone()
    assert rows[0] >= 1

    # 重启后从磁盘恢复，持久化的进度是 10；内存缓存始终最新为 11
    reg2 = TaskRegistry(db_path=reg._db_path)
    try:
        # 磁盘只存了跨 10% 边界的进度
        assert reg2.get("c1:n1")["progress"] == 10
    finally:
        reg2.close()


def test_terminal_state_always_persisted(tmp_registry):
    reg = tmp_registry
    reg.set("c1:n2", {"status": "running", "progress": 50})
    reg.update("c1:n2", status="success", image_url="/assets/2026/07/a.png")

    reg2 = TaskRegistry(db_path=reg._db_path)
    try:
        rec = reg2.get("c1:n2")
        assert rec["status"] == "success"
        assert rec["image_url"] == "/assets/2026/07/a.png"
    finally:
        reg2.close()


def test_running_tasks_preserved_for_resume(tmp_registry):
    """运行中任务在 SQLite 中保持 running，供 resume_interrupted_nodes 在启动时恢复。"""
    reg = tmp_registry
    reg.set("c1:n3", {"status": "running", "progress": 60, "external_task_id": "rh-123"})
    reg.set("c1:n5", {"status": "success", "progress": 100})

    reg2 = TaskRegistry(db_path=reg._db_path)
    try:
        # SQLite write-through 会保留真实 running 状态
        assert reg2.get("c1:n3")["status"] == "running"
        assert reg2.get("c1:n3")["external_task_id"] == "rh-123"
        assert reg2.get("c1:n5")["status"] == "success"
    finally:
        reg2.close()


def test_find_canvas_image_url_priority(tmp_registry):
    reg = tmp_registry
    reg.set("c1:img1", {"status": "success", "node_type": "image_input", "image_url": "/assets/img1.png"})
    reg.set("c1:gpt1", {"status": "success", "node_type": "gpt_image", "image_url": "/assets/gpt1.png"})
    assert reg.find_canvas_image_url("c1", "nX") == "/assets/img1.png"
    reg._tasks.pop("c1:img1")
    assert reg.find_canvas_image_url("c1", "nX") == "/assets/gpt1.png"


def test_get_canvas_nodes(tmp_registry):
    reg = tmp_registry
    reg.set("c1:n1", {"status": "running", "node_id": "n1", "progress": 30, "video_url": "/v.mp4"})
    nodes = reg.get_canvas_nodes("c1")
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == "n1"
    assert nodes[0]["status"] == "running"
    assert nodes[0]["video_url"] == "/v.mp4"
