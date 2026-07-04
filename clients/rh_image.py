"""RunningHub 工作流生图/生视频适配层（异步渠道）。

接入 RH AI 应用工作流 + RH 稳定版原生 API：
- rh_gpt_image_i2i:    workflow 2046794946094571522（gpt-image-2 低价版图生图）
- rh_gpt_image_t2i:    workflow 2046794551444119554（gpt-image-2 低价版文生图）
- nano_banana_pro:     workflow 1965678974313578497（nano banana pro）
- nano_banana_2:       workflow 2067967606665076738（nano banana 2.0，支持 1-4 张参考图）
- seedance_ff:         workflow 2070317987621593089（seedance 首尾帧视频生成）
- rh_gpt_image_official: 原生 API rhart-image-g-2-official（gpt-image-2 稳定版）
- flux_klein_9b:       原生 API rhart-image/f-2-klein-9b/edit（FLUX.2 Klein 9B 编辑）
- seedream_v4:         原生 API seedream-v4/image-to-image（字节 Seedream V4 图生图）
- seedream_v5_lite:    原生 API seedream-v5-lite/image-to-image（Seedream V5 Lite 图生图）
- midjourney_v7:       workflow 2001619198646317058（Midjourney V7 文生图）
- flux2:               workflow 2072562039796625409（flux2 图生图）
- krea2:               workflow 2072870243164311554（krea2 满血版文生图）

统一流程：上传图片 → 提交工作流/原生 API → 轮询 → 下载结果 bytes。
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
WF_MJ_V7 = "2001619198646317058"             # Midjourney V7 文生图
WF_FLUX2_I2I = "2072562039796625409"         # flux2 图生图
WF_KREA2_T2I = "2072870243164311554"         # krea2 满血版文生图

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


async def _download_first_image(result: dict) -> bytes:
    """从 RH 工作流成功结果下载首张图片。"""
    results = result.get("results") or []
    for r in results:
        url = r.get("url")
        if url and (r.get("outputType") in ("png", "jpg", "jpeg", "webp") or url):
            c = get_client()
            dl = await c.get(url, timeout=120)
            dl.raise_for_status()
            return dl.content
    raise RuntimeError(f"RH 工作流成功但无图片结果: {result}")


async def _download_first_video(result: dict) -> bytes:
    """从 RH 工作流成功结果下载首个视频。"""
    results = result.get("results") or []
    for r in results:
        url = r.get("url")
        if url and r.get("outputType") in ("mp4", "video", None):
            c = get_client()
            dl = await c.get(url, timeout=120)
            dl.raise_for_status()
            return dl.content
    raise RuntimeError(f"RH 视频工作流成功但无视频结果: {result}")


async def _poll_task(
    task_id: str, on_progress, timeout: float, interval: float, download_fn
) -> bytes:
    """通用轮询：query_task 循环 + 超时前最后查一次兜底 + 下载结果。

    工作流渠道和原生 API 渠道共用此逻辑。
    """
    elapsed = 0.0
    while elapsed < timeout:
        result = await runninghub.query_task(task_id)
        status = result.get("status", "")
        if on_progress:
            on_progress(status)
        if status == "SUCCESS":
            return await download_fn(result)
        if status == "FAILED":
            raise RuntimeError(
                f"RH 任务失败: {result.get('errorMessage', '')} "
                f"errorCode={result.get('errorCode', '')}"
            )
        await asyncio.sleep(interval)
        elapsed += interval

    # 超时前最后查一次（任务可能在超时边界完成）
    final = await runninghub.query_task(task_id)
    if final.get("status") == "SUCCESS":
        return await download_fn(final)
    if final.get("status") == "FAILED":
        raise RuntimeError(
            f"RH 任务失败: {final.get('errorMessage', '')} errorCode={final.get('errorCode', '')}"
        )
    raise RuntimeError(
        f"RH 任务超时（{timeout}s），task_id={task_id}，最后状态: {final.get('status')}"
    )


async def _run_workflow_and_wait(
    workflow_id: str, node_info_list: list[dict], on_progress=None, on_submitted=None
) -> bytes:
    """提交 AI App 工作流 + 轮询 + 下载首张图片。"""
    if not config.RUNNINGHUB_API_KEY:
        raise RuntimeError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")
    task_id = await _submit_workflow(workflow_id, node_info_list)
    if on_submitted:
        on_submitted(task_id)
    return await _poll_task(
        task_id, on_progress, config.RH_IMAGE_POLL_TIMEOUT,
        config.RH_IMAGE_POLL_INTERVAL, _download_first_image,
    )


async def _run_workflow_and_wait_video(
    workflow_id: str, node_info_list: list[dict], on_progress=None, on_submitted=None
) -> bytes:
    """提交 AI App 工作流 + 轮询 + 下载首个视频。"""
    if not config.RUNNINGHUB_API_KEY:
        raise RuntimeError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")
    task_id = await _submit_workflow(workflow_id, node_info_list)
    if on_submitted:
        on_submitted(task_id)
    return await _poll_task(
        task_id, on_progress, config.SEEDANCE_POLL_TIMEOUT,
        config.SEEDANCE_POLL_INTERVAL, _download_first_video,
    )


async def _rh_official_submit_and_poll(
    endpoint: str, payload: dict, on_progress=None, on_submitted=None
) -> bytes:
    """提交 RH 稳定版原生 API + 轮询 + 下载首图（图生图/文生图共用）。"""
    if not config.RUNNINGHUB_API_KEY:
        raise RuntimeError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")
    client = get_client()
    resp = await client.post(
        f"{config.RUNNINGHUB_BASE_URL}/{endpoint}",
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
            f"RH 稳定版提交失败: {data.get('errorCode')} {data.get('errorMessage', '')}"
        )
    task_id = data["taskId"]
    if on_submitted:
        on_submitted(task_id)
    return await _poll_task(
        task_id, on_progress, config.RH_IMAGE_POLL_TIMEOUT,
        config.RH_IMAGE_POLL_INTERVAL, _download_first_image,
    )


async def rh_gpt_image_official(
    image_bytes_list: list[bytes],
    prompt: str,
    aspect_ratio: str = "16:9",
    resolution: str = "2k",
    quality: str = "medium",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """RH gpt-image-2 官方稳定版图生图（原生 API image-to-image）。

    imageUrls 数组直接传 1-10 张参考图，无需 nodeId 映射（避免默认图混入）。
    """
    if not image_bytes_list:
        raise ValueError("rh_gpt_image_official 图生图至少需要 1 张参考图")

    # 上传所有图片到 RH，拿 download_url 组成 imageUrls
    image_urls = []
    for i, img_bytes in enumerate(image_bytes_list[:10]):  # API 限制 1-10 张
        url = await runninghub.upload_image(img_bytes, f"image{i + 1}.png")
        image_urls.append(url)

    payload = {
        "prompt": prompt,
        "imageUrls": image_urls,
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
        "quality": quality,
    }
    return await _rh_official_submit_and_poll(
        "rhart-image-g-2-official/image-to-image", payload, on_progress, on_submitted
    )


async def rh_gpt_image_official_t2i(
    prompt: str,
    aspect_ratio: str = "16:9",
    resolution: str = "2k",
    quality: str = "medium",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """RH gpt-image-2 官方稳定版文生图（原生 API text-to-image，无参考图）。"""
    payload = {
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "resolution": resolution,
        "quality": quality,
    }
    return await _rh_official_submit_and_poll(
        "rhart-image-g-2-official/text-to-image", payload, on_progress, on_submitted
    )


async def flux_klein_9b_edit(
    image_bytes: bytes,
    prompt: str,
    aspect_ratio: str = "1:1",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """FLUX.2 Klein 9B 图像编辑（原生 API rhart-image/f-2-klein-9b/edit）。

    单张参考图 + prompt 进行高精度编辑，支持 aspectRatio 或 auto。
    """
    if not image_bytes:
        raise ValueError("flux_klein_9b 至少需要 1 张参考图")
    image_url = await runninghub.upload_image(image_bytes, "image.png")
    payload = {
        "imageUrl": image_url,
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "outputFormat": "png",
    }
    return await _rh_official_submit_and_poll(
        "rhart-image/f-2-klein-9b/edit", payload, on_progress, on_submitted
    )


async def seedream_v4_i2i(
    image_bytes_list: list[bytes],
    prompt: str,
    resolution: str = "2k",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """Seedream V4 图生图（原生 API seedream-v4/image-to-image）。

    支持 1-10 张参考图，resolution 优先于 width/height。
    """
    if not image_bytes_list:
        raise ValueError("seedream_v4 至少需要 1 张参考图")
    image_urls = []
    for i, img_bytes in enumerate(image_bytes_list[:10]):
        url = await runninghub.upload_image(img_bytes, f"image{i + 1}.png")
        image_urls.append(url)
    payload = {
        "prompt": prompt,
        "imageUrls": image_urls,
        "resolution": resolution,
        "maxImages": 1,
    }
    return await _rh_official_submit_and_poll(
        "seedream-v4/image-to-image", payload, on_progress, on_submitted
    )


async def seedream_v5_lite_i2i(
    image_bytes_list: list[bytes],
    prompt: str,
    resolution: str = "2k",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """Seedream V5 Lite 图生图（原生 API seedream-v5-lite/image-to-image）。

    支持 1-10 张参考图，resolution 优先于 width/height。
    """
    if not image_bytes_list:
        raise ValueError("seedream_v5_lite 至少需要 1 张参考图")
    image_urls = []
    for i, img_bytes in enumerate(image_bytes_list[:10]):
        url = await runninghub.upload_image(img_bytes, f"image{i + 1}.png")
        image_urls.append(url)
    payload = {
        "prompt": prompt,
        "imageUrls": image_urls,
        "resolution": resolution,
        "maxImages": 1,
    }
    return await _rh_official_submit_and_poll(
        "seedream-v5-lite/image-to-image", payload, on_progress, on_submitted
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


async def mj_v7_t2i(
    prompt: str,
    aspect_ratio: str = "3:4",
    mj_version: str = "Midjourney V7",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """Midjourney V7 文生图（workflow 2001619198646317058）。

    纯文生图，无参考图。支持选择 MJ 版本和比例。
    """
    nodes = [
        _node("6", "text", prompt, "提示词"),
        _node("13", "aspect_rate", aspect_ratio, "比例"),
        _node("13", "model_selected", mj_version, "MJ版本"),
        _node("13", "upscale_selection", "1", "放大选择"),
        _node("13", "active_weight", "100", "活跃权重"),
        _node("13", "reference_type", "--oref", "参考类型"),
        _node("1", "select", "1", "选择"),
        _node("14", "seed", "1139", "种子"),
        _node("13", "seed", "2188598652", "种子"),
    ]
    return await _run_workflow_and_wait(WF_MJ_V7, nodes, on_progress, on_submitted)


# flux2 图生图 aspect_ratio → (width, height) 映射
_FLUX2_ASPECT_SIZES = {
    "1:1": (1024, 1024),
    "9:16": (720, 1280),
    "16:9": (1280, 720),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "3:2": (1152, 768),
    "2:3": (768, 1152),
}


async def flux2_i2i(
    image_bytes: bytes,
    prompt: str,
    aspect_ratio: str = "9:16",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """flux2 图生图（workflow 2072562039796625409）。

    单张参考图 + prompt，通过 aspect_ratio 映射到 width/height。
    """
    if not image_bytes:
        raise ValueError("flux2 至少需要 1 张参考图")
    img_url = await runninghub.upload_image(image_bytes, "image.png")
    width, height = _FLUX2_ASPECT_SIZES.get(aspect_ratio, (720, 1280))
    nodes = [
        _node("30", "image", img_url, "参考图"),
        _node("29", "prompt", prompt, "提示词"),
        _node("36", "value", str(width), "宽度"),
        _node("37", "value", str(height), "高度"),
    ]
    return await _run_workflow_and_wait(WF_FLUX2_I2I, nodes, on_progress, on_submitted)


async def krea2_t2i(
    prompt: str,
    aspect_ratio: str = "9:16 (Portrait Widescreen)",
    on_progress=None,
    on_submitted=None,
) -> bytes:
    """krea2 满血版文生图（workflow 2072870243164311554）。

    纯文生图，无参考图。aspect_ratio 须为完整字符串（如 "9:16 (Portrait Widescreen)"）。
    """
    nodes = [
        _node("12", "text", prompt, "提示词"),
        _node("11", "aspect_ratio", aspect_ratio, "比例"),
        _node("11", "megapixels", "1", "兆像素"),
        _node("2", "sampler_name", "euler", "采样器"),
        _node("2", "scheduler", "simple", "调度器"),
        _node("2", "steps", "8", "步数"),
        _node("9", "lora_name", "karin.safetensors", "LoRA"),
        _node("9", "strength_model", "1", "模型强度"),
        _node("10", "batch_size", "1", "批次大小"),
    ]
    return await _run_workflow_and_wait(WF_KREA2_T2I, nodes, on_progress, on_submitted)
