"""Phase 1 兼容：旧单任务 API（create_task / execute_mock / execute_character）。"""
import asyncio
import logging
import struct
import uuid
import zlib

from clients import gpt_image
from storage import storage
from ._shared import SEM, _background_tasks, classify_error, logger
from .registry import registry

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
        err_info = classify_error(str(e))
        registry.update(task_id, status="failed", error=f"[{err_info['code']}] {err_info['label']}: {e}")


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
    # （画布路径走 executors/gpt_image.py 的 generate_character 图片拼接换装）
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
