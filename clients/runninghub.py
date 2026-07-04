"""RunningHub API 客户端：seedance 图生视频 + sparkvideo 多模态视频。

支持渠道：
- official（官方稳定版）：4/8/12s，无 aspectRatio，图片须 720x1280 或 1280x720
- low_cost（低价版）：10/15s，有 aspectRatio 9:16/16:9
- seedance_2.0（多模态高品质）：多模态参考/视频编辑/续写，4-15s
- seedance_2.0_fast（多模态快速版）：同上，更快生成速度
- seedance_2.0_mini（图生视频）：高性价比批量，首帧/首尾帧，4-15s

流程：上传图片/视频 → 提交任务 → 轮询任务状态 → 返回视频 URL。
视频 URL 24h 过期，由调用方负责下载转存。
"""
import asyncio

import config
from clients.http_client import get_client

# 渠道配置
_CHANNELS = {
    "official": {
        "endpoint": "/rhart-video-s-official/image-to-video",
        "durations": ["4", "8", "12"],
        "has_aspect_ratio": False,
    },
    "low_cost": {
        "endpoint": "/rhart-video-s/image-to-video",
        "durations": ["10", "15"],
        "has_aspect_ratio": True,
    },
}


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.RUNNINGHUB_API_KEY}",
        "Content-Type": "application/json",
    }


def _get_channel() -> dict:
    return _CHANNELS.get(config.SEEDANCE_CHANNEL, _CHANNELS["official"])


async def upload_image(image_bytes: bytes, filename: str = "image.png",
                       content_type: str = "image/png") -> str:
    """上传本地文件到 RunningHub，返回 download_url（1 天有效）。

    content_type 默认 image/png，上传视频时传 video/mp4。
    """
    headers = {"Authorization": f"Bearer {config.RUNNINGHUB_API_KEY}"}
    client = get_client()
    resp = await client.post(
        f"{config.RUNNINGHUB_BASE_URL}/media/upload/binary",
        headers=headers,
        files={"file": (filename, image_bytes, content_type)},
        timeout=config.RUNNINGHUB_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"RunningHub 上传失败: {data.get('message', data)}")
    return data["data"]["download_url"]


async def image_to_video(
    image_url: str,
    prompt: str,
    duration: str = "8",
    aspect_ratio: str = "9:16",
) -> str:
    """提交图生视频任务，返回 task_id。

    根据 config.SEEDANCE_CHANNEL 自动选择端点和参数格式：
    - official: 不传 aspectRatio，duration 限 4/8/12
    - low_cost: 传 aspectRatio，duration 限 10/15

    如果 duration 不在当前渠道合法值中，自动选最接近的。
    """
    ch = _get_channel()

    # 时长不合法时自动调整到最接近的合法值
    if duration not in ch["durations"]:
        duration = min(ch["durations"], key=lambda d: abs(int(d) - int(duration)))

    payload = {
        "imageUrl": image_url,
        "duration": duration,
        "prompt": prompt,
    }
    if ch["has_aspect_ratio"]:
        payload["aspectRatio"] = aspect_ratio

    endpoint = f"{config.RUNNINGHUB_BASE_URL}{ch['endpoint']}"
    client = get_client()
    resp = await client.post(endpoint, headers=_headers(), json=payload, timeout=config.RUNNINGHUB_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode"):
        raise RuntimeError(
            f"RunningHub 提交失败: {data.get('errorCode')} {data.get('errorMessage', '')}"
        )
    return data["taskId"]


async def sparkvideo_submit(
    prompt: str,
    resolution: str = "720p",
    duration: str = "5",
    image_urls: list[str] | None = None,
    video_urls: list[str] | None = None,
    ratio: str = "adaptive",
    generate_audio: bool = False,
    real_person_mode: bool = False,
    return_last_frame: bool = False,
    seed: int = -1,
    fast: bool = False,
) -> str:
    """提交 seedance 2.0 / 2.0 Fast 多模态视频生成任务，返回 task_id。

    Args:
        fast: True → sparkvideo-2.0-fast（快速版），False → sparkvideo-2.0（高品质版）
        image_urls: 参考图片 URL 列表（0-9 张，需先 upload_image 上传到 RH）
        video_urls: 参考视频 URL 列表（0-3 个，用于视频编辑/续写）
        ratio: 视频宽高比，支持 adaptive/16:9/4:3/1:1/3:4/9:16/21:9
    """
    endpoint = (
        "rhart-video/sparkvideo-2.0-fast/multimodal-video" if fast
        else "rhart-video/sparkvideo-2.0/multimodal-video"
    )
    payload = {
        "prompt": prompt,
        "resolution": resolution,
        "duration": duration,
        "ratio": ratio,
        "generateAudio": generate_audio,
        "realPersonMode": real_person_mode,
        "returnLastFrame": return_last_frame,
        "seed": seed,
    }
    if image_urls:
        payload["imageUrls"] = image_urls
    if video_urls:
        payload["videoUrls"] = video_urls

    client = get_client()
    resp = await client.post(
        f"{config.RUNNINGHUB_BASE_URL}/{endpoint}",
        headers=_headers(), json=payload,
        timeout=config.RUNNINGHUB_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode"):
        raise RuntimeError(
            f"RunningHub 提交失败: {data.get('errorCode')} {data.get('errorMessage', '')}"
        )
    return data["taskId"]


async def sparkvideo_mini_submit(
    first_frame_url: str,
    prompt: str | None = None,
    resolution: str = "720p",
    duration: str = "5",
    last_frame_url: str | None = None,
    ratio: str = "adaptive",
    generate_audio: bool = False,
    real_person_mode: bool = False,
    return_last_frame: bool = False,
    seed: int = -1,
) -> str:
    """提交 seedance 2.0 Mini 图生视频任务，返回 task_id。

    首帧必填，尾帧可选（首尾帧模式）。prompt 可选（传 None 时 API 使用默认）。
    480p/720p 为原生输出，1080p/2k/4k 先 720p 生成再超分。
    """
    payload = {
        "firstFrameUrl": first_frame_url,
        "resolution": resolution,
        "duration": duration,
        "ratio": ratio,
        "generateAudio": generate_audio,
        "realPersonMode": real_person_mode,
        "returnLastFrame": return_last_frame,
        "seed": seed,
    }
    if prompt:
        payload["prompt"] = prompt
    if last_frame_url:
        payload["lastFrameUrl"] = last_frame_url

    client = get_client()
    resp = await client.post(
        f"{config.RUNNINGHUB_BASE_URL}/rhart-video/sparkvideo-2.0-mini/image-to-video",
        headers=_headers(), json=payload,
        timeout=config.RUNNINGHUB_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode"):
        raise RuntimeError(
            f"RunningHub 提交失败: {data.get('errorCode')} {data.get('errorMessage', '')}"
        )
    return data["taskId"]


async def query_task(task_id: str) -> dict:
    """查询任务状态。

    Returns:
        {
            "status": "QUEUED" | "RUNNING" | "SUCCESS" | "FAILED",
            "results": [{"url": "...", "outputType": "mp4"}] | None,
            "errorCode": str,
            "errorMessage": str,
        }
    """
    client = get_client()
    resp = await client.post(
        f"{config.RUNNINGHUB_BASE_URL}/query",
        headers=_headers(),
        json={"taskId": task_id},
        timeout=config.RUNNINGHUB_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


async def wait_for_result(
    task_id: str,
    on_progress=None,
) -> str:
    """轮询任务直到完成，返回视频 URL。

    Args:
        task_id: image_to_video 返回的任务 ID
        on_progress: 可选回调 fn(status: str) → None，用于上报进度

    Returns:
        video_url: 视频下载链接（24h 有效，调用方需立即下载转存）

    Raises:
        RuntimeError: 任务失败或超时
    """
    elapsed = 0.0
    while elapsed < config.SEEDANCE_POLL_TIMEOUT:
        result = await query_task(task_id)
        status = result.get("status", "")

        if on_progress:
            on_progress(status)

        if status == "SUCCESS":
            results = result.get("results") or []
            for r in results:
                if r.get("outputType") == "mp4" or r.get("url"):
                    return r["url"]
            raise RuntimeError(f"任务成功但无视频结果: {result}")

        if status == "FAILED":
            raise RuntimeError(
                f"视频生成失败: {result.get('errorMessage', '')} "
                f"errorCode={result.get('errorCode', '')}"
            )

        await asyncio.sleep(config.SEEDANCE_POLL_INTERVAL)
        elapsed += config.SEEDANCE_POLL_INTERVAL

    raise RuntimeError(
        f"视频生成超时（{config.SEEDANCE_POLL_TIMEOUT}s），task_id={task_id}"
    )
