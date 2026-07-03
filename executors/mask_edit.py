"""mask_edit 执行器：透传原图 + 生成遮罩。"""
from typing import Callable

from node_types import MaskEditInput, NodeOutput
from storage import storage
import logging

logger = logging.getLogger("executors.mask_edit")


async def execute(input: MaskEditInput, on_progress: Callable[[int], None],
                  on_submitted: Callable[[str], None] | None = None) -> NodeOutput:
    if not input.image:
        raise ValueError("mask_edit 节点缺少输入图片")

    on_progress(10)
    mask_url = input.mask_url

    if input.mask_mode == "auto_face":
        from mask_service import detect_face_mask, generate_full_mask
        ref_bytes = await storage.download(input.image)
        on_progress(30)
        try:
            mask_bytes = detect_face_mask(
                ref_bytes, expand=input.expand, method=input.detect_method,
                face_index=input.face_index, mask_value=input.mask_value,
            )
        except ValueError as e:
            # 人脸检测失败：fallback 到全图遮罩
            logger.warning("mask_edit auto_face failed: %s", e)
            mask_bytes = generate_full_mask(ref_bytes)
        mask_url = await storage.save(mask_bytes, "png")
        on_progress(70)
    elif input.mask_mode == "auto_full":
        from mask_service import generate_full_mask
        ref_bytes = await storage.download(input.image)
        on_progress(40)
        mask_bytes = generate_full_mask(ref_bytes)
        mask_url = await storage.save(mask_bytes, "png")
        on_progress(70)
    else:
        # manual
        if not mask_url:
            raise ValueError("mask_edit 节点未绘制遮罩（请双击节点编辑遮罩，或切换自动模式）")

    on_progress(90)
    return NodeOutput(image_url=input.image, mask_url=mask_url)
