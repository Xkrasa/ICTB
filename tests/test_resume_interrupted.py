"""RunningHub 任务重启后续跑测试。"""
import asyncio

import pytest

import orchestrator
from executors import NODE_EXECUTORS
from orchestrator.registry import registry


class FakeSeedance:
    def __init__(self):
        self.calls = []

    async def resume(self, external_task_id, channel, on_progress):
        self.calls.append((external_task_id, channel))
        on_progress(50)
        from node_types import NodeOutput
        return NodeOutput(video_url="/assets/2026/07/resumed.mp4")


@pytest.fixture
def clean_registry(monkeypatch):
    """每个测试前清理相关 canvas 记录。"""
    keys_before = set(registry._tasks.keys())
    old_conn = registry._conn
    yield
    for k in list(registry._tasks.keys()):
        if k not in keys_before:
            del registry._tasks[k]
    registry._last_persisted_progress = {}
    registry._conn = old_conn


@pytest.mark.asyncio
async def test_resume_interrupted_seedance_video(clean_registry, monkeypatch):
    fake = FakeSeedance()
    monkeypatch.setitem(NODE_EXECUTORS, "seedance_video", fake)

    registry.set("c1:vid1", {
        "canvas_id": "c1", "node_id": "vid1", "node_type": "seedance_video",
        "status": "running", "progress": 25,
        "external_task_id": "rh-task-123",
    })
    registry.set("c1:vid2", {
        "canvas_id": "c1", "node_id": "vid2", "node_type": "seedance_video",
        "status": "pending", "progress": 0,
        "external_task_id": "rh-task-456",
    })
    registry.set("c1:img1", {
        "canvas_id": "c1", "node_id": "img1", "node_type": "gpt_image",
        "status": "running", "progress": 50,
        "external_task_id": "rh-task-789",
    })

    tasks = await orchestrator.resume_interrupted_nodes()
    assert len(tasks) == 2
    await asyncio.gather(*tasks)

    assert len(fake.calls) == 2
    assert ("rh-task-123", "") in fake.calls
    assert ("rh-task-456", "") in fake.calls
    assert registry.get("c1:vid1")["status"] == "success"
    assert registry.get("c1:vid1")["video_url"] == "/assets/2026/07/resumed.mp4"
    assert registry.get("c1:vid2")["status"] == "success"
    # gpt_image 不在恢复列表中，保持 running
    assert registry.get("c1:img1")["status"] == "running"


@pytest.mark.asyncio
async def test_no_resume_for_terminal_states(clean_registry):
    registry.set("c1:vid3", {
        "canvas_id": "c1", "node_id": "vid3", "node_type": "seedance_video",
        "status": "success", "progress": 100,
        "external_task_id": "rh-task-done",
    })
    tasks = await orchestrator.resume_interrupted_nodes()
    assert len(tasks) == 0
