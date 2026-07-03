"""remove_bg 执行器：RunningHub AI App 抠图 → 透明 PNG。"""
import asyncio
from typing import Callable

import config
from clients import runninghub
from clients.http_client import get_client
from storage import storage

from node_types import RemoveBgInput, NodeOutput
from executors._helpers import make_rh_progress_cb


async def execute(input: RemoveBgInput, on_progress: Callable[[int], None],
                  on_submitted: Callable[[str], None] | None = None) -> NodeOutput:
    if not config.RUNNINGHUB_API_KEY:
        raise ValueError("未配置 RUNNINGHUB_API_KEY，请在 .env 中设置")
    if not input.image:
        raise ValueError("remove_bg 节点缺少输入图片")

    on_progress(5)
    ref_bytes = await storage.download(input.image)
    on_progress(15)

    # 上传到 RunningHub
    img_url = await runninghub.upload_image(ref_bytes, "remove_bg.png")
    on_progress(25)

    # 提交 AI App 抠图工作流
    workflow_id = config.RH_REMOVE_BG_WORKFLOW_ID
    nodes = [
        {"nodeId": "3", "fieldName": "image", "fieldValue": img_url, "description": "上传图片"},
    ]
    payload = {
        "nodeInfoList": nodes,
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
            f"RH 抠图提交失败: {data.get('errorCode')} {data.get('errorMessage', '')}"
        )
    rh_task_id = data["taskId"]

    if on_submitted:
        on_submitted(rh_task_id)
    on_progress(35)

    # 轮询任务状态
    elapsed = 0.0
    while elapsed < config.RH_REMOVE_BG_POLL_TIMEOUT:
        result = await runninghub.query_task(rh_task_id)
        status = result.get("status", "")

        if status == "SUCCESS":
            results = result.get("results") or []
            for r in results:
                url = r.get("url")
                if url:
                    c = get_client()
                    dl = await c.get(url, timeout=120)
                    dl.raise_for_status()
                    out_url = await storage.save(dl.content, "png")
                    on_progress(95)
                    return NodeOutput(image_url=out_url)
            raise RuntimeError(f"RH 抠图成功但无图片结果: {result}")

        if status == "FAILED":
            raise RuntimeError(
                f"RH 抠图失败: {result.get('errorMessage', '')} "
                f"errorCode={result.get('errorCode', '')}"
            )

        progress = min(35 + int(elapsed / config.RH_REMOVE_BG_POLL_TIMEOUT * 55), 90)
        on_progress(progress)

        await asyncio.sleep(config.RH_REMOVE_BG_POLL_INTERVAL)
        elapsed += config.RH_REMOVE_BG_POLL_INTERVAL

    raise RuntimeError(
        f"RH 抠图超时（{config.RH_REMOVE_BG_POLL_TIMEOUT}s），task_id={rh_task_id}"
    )
