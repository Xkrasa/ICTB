"""异步任务编排引擎。

- TaskRegistry：内存任务注册表，方法签名兼容未来 SQLite 实现
- SEM：asyncio.Semaphore(3) 并发闸，卡死 API 并发上限
- create_task：注册 pending 任务并启动后台协程，立即返回 task_id（不阻塞）
- 每个任务独立状态机，互不干扰
"""
import asyncio
import struct
import time
import uuid
import zlib

from storage import storage

# 并发闸：最多 3 个任务同时执行（防止 API 账单失控，后续按配额调整）
SEM = asyncio.Semaphore(3)

# 后台任务引用集合，防止被 GC 回收
_background_tasks: set = set()


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

# stage name -> async executor(task_id, params)
_STAGE_EXECUTORS: dict = {}


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
    """注册 pending 任务并启动后台协程，立即返回 task_id（不阻塞）"""
    task_id = uuid.uuid4().hex
    registry.set(task_id, _new_record(task_id, workflow_id, stage))
    t = asyncio.create_task(_run(task_id, stage, params))
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)
    return task_id


async def _run(task_id: str, stage: str, params: dict) -> None:
    """共享并发闸，执行对应阶段；成功设 success，异常设 failed(error)"""
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


async def execute_mock(task_id: str, params: dict) -> None:
    """Mock 阶段：推进进度 0→100（约 5s），结束落一个真实可访问的占位 PNG"""
    for p in range(0, 101, 10):
        registry.update(task_id, progress=p)
        await asyncio.sleep(0.5)
    # 落占位资产，让前端拿到的 URL 真实可打开（支撑验收点 5）
    url = await storage.save(_placeholder_png(), "png")
    rec = registry.get(task_id)
    if rec is not None:
        assets = dict(rec["assets"])
        assets["character_png"] = url
        registry.update(task_id, assets=assets)


def _placeholder_png() -> bytes:
    """生成一个最小合法 1x1 灰度 PNG（浏览器可正常渲染）"""
    raw = b"\x00\xc0"  # filter byte + 灰度像素 0xc0
    compressed = zlib.compress(raw)

    def _chunk(typ: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + typ
            + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)  # 1x1, 8-bit grayscale
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")


_STAGE_EXECUTORS["mock"] = execute_mock
