"""image_input 执行器：上传图直接作为产出。"""
import asyncio
from typing import Callable

from node_types import ImageInputInput, NodeOutput


async def execute(input: ImageInputInput, on_progress: Callable[[int], None],
                  on_submitted: Callable[[str], None] | None = None) -> NodeOutput:
    if not input.image_url:
        raise ValueError("image_input 节点未上传图片")
    on_progress(50)
    await asyncio.sleep(0.1)  # 让 UI 有时间渲染
    on_progress(100)
    return NodeOutput(image_url=input.image_url)
