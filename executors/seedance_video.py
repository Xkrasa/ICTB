"""seedance_video 执行器：图生视频 / 多模态视频。

6 渠道：
- first_last_frame（首尾帧）：RH AI App 工作流，首帧→尾帧过渡
- official（官方稳定版）：seedance 原生 API，4/8/12s
- low_cost（低价版）：seedance 原生 API，10/15s
- seedance_2.0（多模态高品质）：sparkvideo-2.0，多模态参考/视频编辑/续写
- seedance_2.0_fast（多模态快速版）：sparkvideo-2.0-fast，同上更快
- seedance_2.0_mini（图生视频）：sparkvideo-2.0-mini，高性价比首帧/首尾帧
"""
from typing import Callable

import config
from clients import rh_image, runninghub
from clients.http_client import get_client
from storage import storage

from node_types import SeedanceInput, NodeOutput
from executors._helpers import make_rh_progress_cb


def _make_progress_cb(on_progress: Callable[[int], None], start: int = 20):
    """构造 RH 状态→进度的回调（官方/低价/2.0/Mini 通用）。"""
    cur = [start]

    def cb(status: str) -> None:
        if status == "QUEUED":
            cur[0] = start
            on_progress(start)
        elif status == "RUNNING":
            cur[0] = min(cur[0] + 5, 80)
            on_progress(cur[0])

    return cb


async def _download_and_save_video(video_url: str, on_progress: Callable[[int], None]) -> str:
    """下载 RH 视频 URL 并转存为本地永久 URL。"""
    on_progress(85)
    client = get_client()
    resp = await client.get(video_url, timeout=120)
    resp.raise_for_status()
    url = await storage.save(resp.content, "mp4")
    on_progress(95)
    return url


async def execute(input: SeedanceInput, on_progress: Callable[[int], None],
                  on_submitted: Callable[[str], None] | None = None) -> NodeOutput:
    if not config.RUNNINGHUB_API_KEY:
        raise ValueError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")

    is_spark = input.channel in ("seedance_2.0", "seedance_2.0_fast")
    if not is_spark and not input.first_frame:
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

    # ── seedance 2.0 / 2.0 Fast 多模态模式 ──
    if is_spark:
        fast = input.channel == "seedance_2.0_fast"
        on_progress(5)

        image_urls = []
        if input.first_frame:
            ref_bytes = await storage.download(input.first_frame)
            rh_url = await runninghub.upload_image(ref_bytes, "image.png")
            image_urls.append(rh_url)

        video_urls = []
        if input.video_url:
            video_bytes = await storage.download(input.video_url)
            rh_vurl = await runninghub.upload_image(
                video_bytes, "video.mp4", content_type="video/mp4"
            )
            video_urls.append(rh_vurl)

        on_progress(10)
        task_id = await runninghub.sparkvideo_submit(
            prompt, input.resolution, input.duration,
            image_urls=image_urls or None,
            video_urls=video_urls or None,
            ratio=input.aspect_ratio,
            generate_audio=input.generate_audio,
            real_person_mode=input.real_person_mode,
            fast=fast,
        )
        submitted(task_id)

        cb = _make_progress_cb(on_progress, start=20)
        on_progress(20)
        video_url = await runninghub.wait_for_result(task_id, cb)
        url = await _download_and_save_video(video_url, on_progress)
        return NodeOutput(video_url=url)

    # ── seedance 2.0 Mini 图生视频模式 ──
    if input.channel == "seedance_2.0_mini":
        on_progress(5)
        ref_bytes = await storage.download(input.first_frame)
        rh_first_url = await runninghub.upload_image(ref_bytes, "image.png")

        rh_last_url = None
        if input.last_frame:
            last_bytes = await storage.download(input.last_frame)
            rh_last_url = await runninghub.upload_image(last_bytes, "last_frame.png")

        on_progress(10)
        task_id = await runninghub.sparkvideo_mini_submit(
            rh_first_url,
            prompt=prompt if len(prompt) >= 5 else None,
            resolution=input.resolution,
            duration=input.duration,
            last_frame_url=rh_last_url,
            ratio=input.aspect_ratio,
            generate_audio=input.generate_audio,
            real_person_mode=input.real_person_mode,
        )
        submitted(task_id)

        cb = _make_progress_cb(on_progress, start=20)
        on_progress(20)
        video_url = await runninghub.wait_for_result(task_id, cb)
        url = await _download_and_save_video(video_url, on_progress)
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

    cb = _make_progress_cb(on_progress, start=20)
    on_progress(20)
    video_url = await runninghub.wait_for_result(task_id, cb)
    url = await _download_and_save_video(video_url, on_progress)
    return NodeOutput(video_url=url)


async def resume(external_task_id: str, channel: str,
                 on_progress: Callable[[int], None]) -> NodeOutput:
    """进程重启后恢复 RH 视频任务轮询。

    仅依赖 external_task_id 即可继续查询 RunningHub，无需原始输入参数。
    channel 用于选择正确的进度回调和状态机，但不影响 query_task 接口。
    """
    if not config.RUNNINGHUB_API_KEY:
        raise ValueError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")

    on_progress(20)
    cb = _make_progress_cb(on_progress, start=20)
    video_url = await runninghub.wait_for_result(external_task_id, cb)
    url = await _download_and_save_video(video_url, on_progress)
    return NodeOutput(video_url=url)
