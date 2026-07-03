"""RunningHub 工作流生图/生视频适配层（异步渠道）。

接入 RH AI 应用工作流：
- rh_gpt_image_i2i: workflow 2046794946094571522（gpt-image-2 低价版图生图）
- rh_gpt_image_t2i: workflow 2046794551444119554（gpt-image-2 低价版文生图）
- nano_banana_pro:  workflow 1965678974313578497（nano banana pro）
- nano_banana_2:    workflow 2067967606665076738（nano banana 2.0，支持 1-4 张参考图）
- seedance_ff:      workflow 2070317987621593089（seedance 首尾帧视频生成）

统一流程：上传图片 → 提交工作流 → 轮询 → 下载结果 bytes。
不处理透明背景（按用户决策，由后续 remove_bg 节点处理）。

复用 runninghub.upload_image / query_task / wait_for_result。
"""
import asyncio

import config
from clients import runninghub
from clients.http_client import get_client

# ───────────────────────── 工作流常量 ─────────────────────────

WF_RH_GPT_IMAGE_I2I = "2046794946094571522"  # gpt-image-2 低价版图生图
WF_RH_GPT_IMAGE_T2I = "2046794551444119554"  # gpt-image-2 低价版文生图
WF_NANO_BANANA_PRO = "1965678974313578497"   # nano banana pro
WF_NANO_BANANA_2 = "2067967606665076738"     # nano banana 2.0
WF_SEEDANCE_FF = "2070317987621593089"       # seedance 首尾帧视频生成

# 合法比例（取各工作流的交集，简化前端选项）
ASPECT_RATIOS = ["1:1", "9:16", "16:9", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4"]
RESOLUTIONS = ["1k", "2k", "4k"]


# ───────────────────────── 工作流提交 ─────────────────────────

async def _submit_workflow(workflow_id: str, node_info_list: list[dict]) -> str:
    """提交 RH AI 应用工作流，返回 task_id。"""
    payload = {
        "nodeInfoList": node_info_list,
        "instanceType": "default",
        "usePersonalQueue": "false",
    }
    client = get_client()
    resp = await client.post(
        f"{config.RUNNINGHUB_BASE_URL}/run/ai-app/{workflow_id}",
        headers={
            "Authorization": f"Bearer {config.RUNNINGHUB_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=config.RUNNINGHUB_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errorCode"):
        raise RuntimeError(
            f"RH 工作流提交失败: {data.get('errorCode')} {data.get('errorMessage', '')}"
        )
    return data["taskId"]


async def _run_workflow_and_wait(
    workflow_id: str,
    node_info_list: list[dict],
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """提交 + 轮询 + 下载首张图片，返回 PNG bytes。"""
    if not config.RUNNINGHUB_API_KEY:
        raise RuntimeError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")

    task_id = await _submit_workflow(workflow_id, node_info_list)

    # 通知调用方外部任务 ID（用于持久化预留续跑）
    if on_submitted:
        on_submitted(task_id)

    # 轮询（复用 runninghub.wait_for_result 的查询机制，但提取图片 URL 而非视频）
    elapsed = 0.0
    while elapsed < config.RH_IMAGE_POLL_TIMEOUT:
        result = await runninghub.query_task(task_id)
        status = result.get("status", "")
        if on_progress:
            on_progress(status)
        if status == "SUCCESS":
            results = result.get("results") or []
            for r in results:
                url = r.get("url")
                if url and (r.get("outputType") in ("png", "jpg", "jpeg", "webp") or url):
                    # 下载并返回 bytes（RH URL 24h 过期，由调用方 storage.save 转存）
                    c = get_client()
                    dl = await c.get(url, timeout=120)
                    dl.raise_for_status()
                    return dl.content
            raise RuntimeError(f"RH 工作流成功但无图片结果: {result}")
        if status == "FAILED":
            raise RuntimeError(
                f"RH 工作流失败: {result.get('errorMessage', '')} "
                f"errorCode={result.get('errorCode', '')}"
            )
        await asyncio.sleep(config.RH_IMAGE_POLL_INTERVAL)
        elapsed += config.RH_IMAGE_POLL_INTERVAL

    raise RuntimeError(
        f"RH 工作流超时（{config.RH_IMAGE_POLL_TIMEOUT}s），task_id={task_id}"
    )


async def _run_workflow_and_wait_video(
    workflow_id: str,
    node_info_list: list[dict],
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """提交 + 轮询 + 下载首个视频，返回 mp4 bytes。"""
    if not config.RUNNINGHUB_API_KEY:
        raise RuntimeError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")

    task_id = await _submit_workflow(workflow_id, node_info_list)

    if on_submitted:
        on_submitted(task_id)

    elapsed = 0.0
    while elapsed < config.SEEDANCE_POLL_TIMEOUT:
        result = await runninghub.query_task(task_id)
        status = result.get("status", "")
        if on_progress:
            on_progress(status)
        if status == "SUCCESS":
            results = result.get("results") or []
            for r in results:
                url = r.get("url")
                if url and r.get("outputType") in ("mp4", "video", None):
                    c = get_client()
                    dl = await c.get(url, timeout=120)
                    dl.raise_for_status()
                    return dl.content
            raise RuntimeError(f"RH 视频工作流成功但无视频结果: {result}")
        if status == "FAILED":
            raise RuntimeError(
                f"RH 视频工作流失败: {result.get('errorMessage', '')} "
                f"errorCode={result.get('errorCode', '')}"
            )
        await asyncio.sleep(config.SEEDANCE_POLL_INTERVAL)
        elapsed += config.SEEDANCE_POLL_INTERVAL

    raise RuntimeError(
        f"RH 视频工作流超时（{config.SEEDANCE_POLL_TIMEOUT}s），task_id={task_id}"
    )


def _node(node_id: str, field_name: str, field_value: str, desc: str = "") -> dict:
    """构造 nodeInfoList 单项。"""
    item = {"nodeId": node_id, "fieldName": field_name, "fieldValue": field_value}
    if desc:
        item["description"] = desc
    return item


# ───────────────────────── 3 个工作流高层 API ─────────────────────────

async def rh_gpt_image_i2i(
    image1_bytes: bytes,
    image2_bytes: bytes | None,
    prompt: str,
    aspect_ratio: str = "9:16",
    resolution: str = "1k",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """RH gpt-image-2 低价版图生图（workflow 2046794946094571522）。"""
    img1_url = await runninghub.upload_image(image1_bytes, "image1.png")
    nodes = [_node("3", "image", img1_url, "上传图像1")]
    if image2_bytes:
        img2_url = await runninghub.upload_image(image2_bytes, "image2.png")
        nodes.append(_node("2", "image", img2_url, "上传图像2"))
    nodes.extend([
        _node("4", "aspectRatio", aspect_ratio, "设置比例"),
        _node("4", "resolution", resolution, "分辨率"),
        _node("4", "prompt", prompt, "输入文本"),
    ])
    return await _run_workflow_and_wait(WF_RH_GPT_IMAGE_I2I, nodes, on_progress, on_submitted)


async def rh_gpt_image_t2i(
    prompt: str,
    aspect_ratio: str = "9:16",
    resolution: str = "1k",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """RH gpt-image-2 低价版文生图（workflow 2046794551444119554）。"""
    nodes = [
        _node("18", "aspectRatio", aspect_ratio, "设置比例"),
        _node("18", "resolution", resolution, "分辨率"),
        _node("18", "prompt", prompt, "输入文本"),
    ]
    return await _run_workflow_and_wait(WF_RH_GPT_IMAGE_T2I, nodes, on_progress, on_submitted)


async def nano_banana_pro(
    image_bytes: bytes,
    prompt: str,
    aspect_ratio: str = "9:16",
    resolution: str = "1k",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """nano banana pro（workflow 1965678974313578497）。"""
    img_url = await runninghub.upload_image(image_bytes, "image.png")
    nodes = [
        _node("55", "image", img_url, "图像"),
        _node("54", "text", prompt, "提示词"),
        _node("127", "resolution", resolution, "分辨率"),
        _node("127", "aspectRatio", aspect_ratio, "尺寸比例"),
    ]
    return await _run_workflow_and_wait(WF_NANO_BANANA_PRO, nodes, on_progress, on_submitted)


async def nano_banana_2(
    images: list[bytes],
    prompt: str,
    aspect_ratio: str = "9:16",
    resolution: str = "1k",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """nano banana 2.0（workflow 2067967606665076738）。"""
    if not images:
        raise ValueError("nano_banana_2 至少需要 1 张参考图")
    if len(images) > 4:
        images = images[:4]

    # 上传所有图片
    uploaded = []
    for i, img_bytes in enumerate(images):
        url = await runninghub.upload_image(img_bytes, f"image{i+1}.png")
        uploaded.append(url)

    # 工作流 nodeId 3/4/5/6 对应 image1/2/3/4
    image_node_ids = ["3", "4", "5", "6"]
    nodes = []
    for i, url in enumerate(uploaded):
        desc = "上传图像1（必填）" if i == 0 else f"上传图像{i+1}（选填）"
        nodes.append(_node(image_node_ids[i], "image", url, desc))
    nodes.extend([
        _node("8", "aspectRatio", aspect_ratio, "比例"),
        _node("8", "resolution", resolution, "分辨率"),
        _node("8", "prompt", prompt, "输入文本"),
    ])
    return await _run_workflow_and_wait(WF_NANO_BANANA_2, nodes, on_progress, on_submitted)


async def seedance_first_last_frame(
    first_frame_bytes: bytes,
    last_frame_bytes: bytes | None,
    prompt: str,
    duration: str = "5",
    aspect_ratio: str = "9:16",
    resolution: str = "480p",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """seedance 首尾帧视频生成（workflow 2070317987621593089）。

    首帧必填，尾帧可选（无尾帧时仅首帧生视频）。
    返回 mp4 bytes，由调用方 storage.save 转存。
    """
    first_url = await runninghub.upload_image(first_frame_bytes, "first_frame.png")
    nodes = [_node("50", "image", first_url, "上传首帧")]
    if last_frame_bytes:
        last_url = await runninghub.upload_image(last_frame_bytes, "last_frame.png")
        nodes.append(_node("53", "image", last_url, "上传尾帧"))
    nodes.extend([
        _node("54", "text", prompt, "指令"),
        _node("55", "ratio", aspect_ratio, "比例"),
        _node("55", "resolution", resolution, "分辨率"),
        _node("55", "duration", duration, "时长"),
    ])
    return await _run_workflow_and_wait_video(
        WF_SEEDANCE_FF, nodes, on_progress, on_submitted
    )
