"""RunningHub API 客户端：seedance 图生视频。

流程：上传图片 → 提交图生视频 → 轮询任务状态 → 返回视频 URL。
视频 URL 24h 过期，由调用方负责下载转存。
"""
import asyncio

import httpx

import config


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.RUNNINGHUB_API_KEY}",
        "Content-Type": "application/json",
    }


async def upload_image(image_bytes: bytes, filename: str = "image.png") -> str:
    """上传本地图片到 RunningHub，返回 download_url（1 天有效）。

    用于把本地 assets/ 图片转为 RunningHub 可访问的 URL。
    """
    headers = {"Authorization": f"Bearer {config.RUNNINGHUB_API_KEY}"}
    async with httpx.AsyncClient(timeout=config.RUNNINGHUB_TIMEOUT) as client:
        resp = await client.post(
            f"{config.RUNNINGHUB_BASE_URL}/media/upload/binary",
            headers=headers,
            files={"file": (filename, image_bytes, "image/png")},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"RunningHub 上传失败: {data.get('message', data)}")
        return data["data"]["download_url"]


async def image_to_video(
    image_url: str,
    prompt: str,
    duration: str = "10",
    aspect_ratio: str = "9:16",
    storyboard: bool = False,
) -> str:
    """提交图生视频任务，返回 task_id。

    Args:
        image_url: RunningHub 可访问的图片 URL（通过 upload_image 获取）
        prompt: 视频描述（5-4000 字符）
        duration: 视频时长，枚举 "10" 或 "15"
        aspect_ratio: 宽高比，枚举 "9:16" 或 "16:9"
        storyboard: 是否使用分镜模式

    Returns:
        task_id: 用于后续 query_task 轮询
    """
    payload = {
        "imageUrl": image_url,
        "duration": duration,
        "aspectRatio": aspect_ratio,
        "prompt": prompt,
        "storyboard": storyboard,
    }
    async with httpx.AsyncClient(timeout=config.RUNNINGHUB_TIMEOUT) as client:
        resp = await client.post(
            f"{config.RUNNINGHUB_BASE_URL}/rhart-video-s/image-to-video",
            headers=_headers(),
            json=payload,
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
    async with httpx.AsyncClient(timeout=config.RUNNINGHUB_TIMEOUT) as client:
        resp = await client.post(
            f"{config.RUNNINGHUB_BASE_URL}/query",
            headers=_headers(),
            json={"taskId": task_id},
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
