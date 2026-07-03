"""seedance_video 执行器：图生视频。

3 渠道：
- first_last_frame（首尾帧）：RH AI App 工作流，首帧→尾帧过渡
- official（官方稳定版）：seedance 原生 API，4/8/12s
- low_cost（低价版）：seedance 原生 API，10/15s
"""
from typing import Callable

import config
from clients import rh_image, runninghub
from clients.http_client import get_client
from storage import storage

from node_types import SeedanceInput, NodeOutput
from executors._helpers import make_rh_progress_cb


async def execute(input: SeedanceInput, on_progress: Callable[[int], None],
                  on_submitted: Callable[[str], None] | None = None) -> NodeOutput:
    if not config.RUNNINGHUB_API_KEY:
        raise ValueError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")
    if not input.first_frame:
        raise ValueError("seedance_video 节点缺少输入图片（首帧）")

    prompt = input.prompt
    if len(prompt) < 5:
        prompt = "基于原图生成动态视频，人物自然微笑，缓慢转头。"

    submitted = on_submitted or (lambda _tid: None)

    # ── 首尾帧模式 ──
    if input.channel == "first_last_frame":
        on_progress(5)
        ref_bytes = await storage.download(input.first_frame)
        last_bytes = await storage.download(input.last_frame) if input.last_frame else None
        on_progress(10)
        cb = make_rh_progress_cb(on_progress)
        video_bytes = await rh_image.seedance_first_last_frame(
            ref_bytes, last_bytes, prompt,
            duration=input.duration, aspect_ratio=input.aspect_ratio,
            resolution=input.resolution,
            on_progress=cb, on_submitted=submitted,
        )
        url = await storage.save(video_bytes, "mp4")
        on_progress(95)
        return NodeOutput(video_url=url)

    # ── 官方/低价版模式 ──
    on_progress(5)
    ref_bytes = await storage.download(input.first_frame)

    on_progress(10)
    rh_image_url = await runninghub.upload_image(ref_bytes)

    on_progress(15)
    task_id = await runninghub.image_to_video(
        rh_image_url, prompt, input.duration, input.aspect_ratio
    )
    submitted(task_id)

    # 渐进进度（局部变量，原逻辑读 registry）
    cur = [20]

    def on_status(status: str) -> None:
        if status == "QUEUED":
            cur[0] = 20
            on_progress(20)
        elif status == "RUNNING":
            cur[0] = min(cur[0] + 5, 80)
            on_progress(cur[0])

    on_progress(20)
    video_url = await runninghub.wait_for_result(task_id, on_status)

    on_progress(85)
    client = get_client()
    resp = await client.get(video_url, timeout=120)
    resp.raise_for_status()

    url = await storage.save(resp.content, "mp4")
    on_progress(95)
    return NodeOutput(video_url=url)
