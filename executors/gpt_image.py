"""gpt_image 执行器：参考图 + prompt → PNG。

4 模型分支：
- gpt-image-2: 同步渠道（generations / mask / hair / clothing / edit）
- rh_gpt_image_i2i / nano_banana_pro / nano_banana_2: RH 工作流异步渠道
"""
import logging
from typing import Callable

import config
from clients import gpt_image, rh_image
from storage import storage

from node_types import GptImageInput, NodeOutput
from executors._helpers import make_rh_progress_cb

logger = logging.getLogger("executors.gpt_image")


async def execute(input: GptImageInput, on_progress: Callable[[int], None],
                  on_submitted: Callable[[str], None] | None = None) -> NodeOutput:
    logger.info("exec_gpt_image model=%s", input.model)

    if input.model == "gpt-image-2":
        return await _exec_sync(input, on_progress)

    # RH 工作流异步渠道
    prompt = input.prompt
    if len(prompt) < 5:
        if input.model == "rh_gpt_image_i2i" and not (input.image1 or input.image2):
            prompt = "生成高质量商业海报图像，画面精致，细节丰富。"
        else:
            prompt = "基于参考图生成高质量图像，保持人物特征。"

    on_progress(10)
    cb = make_rh_progress_cb(on_progress)
    submitted = on_submitted or (lambda _tid: None)

    if input.model == "rh_gpt_image_i2i":
        primary_url = input.image1 or input.image2
        if primary_url:
            ref_bytes = await storage.download(primary_url)
            img2_bytes = None
            if input.image1 and input.image2:
                img2_bytes = await storage.download(input.image2)
            png_bytes = await rh_image.rh_gpt_image_i2i(
                ref_bytes, img2_bytes, prompt, input.aspect_ratio, input.resolution,
                on_progress=cb, on_submitted=submitted,
            )
        else:
            png_bytes = await rh_image.rh_gpt_image_t2i(
                prompt, input.aspect_ratio, input.resolution,
                on_progress=cb, on_submitted=submitted,
            )
    elif input.model == "nano_banana_pro":
        if not input.image1:
            raise ValueError("gpt_image 节点缺少输入图片（请连线 image_input 或上游节点）")
        ref_bytes = await storage.download(input.image1)
        png_bytes = await rh_image.nano_banana_pro(
            ref_bytes, prompt, input.aspect_ratio, input.resolution,
            on_progress=cb, on_submitted=submitted,
        )
    elif input.model == "nano_banana_2":
        if not input.image1:
            raise ValueError("gpt_image 节点缺少输入图片（请连线 image_input 或上游节点）")
        ref_bytes = await storage.download(input.image1)
        extra_urls = [input.image2, input.image3_url, input.image4_url,
                      input.hair_url, input.clothing_url]
        extra_urls = [u for u in extra_urls if u]
        images = [ref_bytes]
        for u in extra_urls[:3]:
            images.append(await storage.download(u))
        png_bytes = await rh_image.nano_banana_2(
            images, prompt, input.aspect_ratio, input.resolution,
            on_progress=cb, on_submitted=submitted,
        )
    else:
        raise ValueError(f"gpt_image 节点未知模型: {input.model}")

    url = await storage.save(png_bytes, "png")
    on_progress(95)
    return NodeOutput(image_url=url)


async def _exec_sync(input: GptImageInput, on_progress: Callable[[int], None]) -> NodeOutput:
    """gpt-image-2 同步渠道（generations / mask / hair / clothing / edit）。"""
    size = input.size or input.resolution or config.GPT_IMAGE_SIZE
    ref_url = input.image1

    on_progress(15)

    # 无参考图 → 文生图
    if not ref_url:
        on_progress(25)
        png_bytes = await gpt_image.generate_image(
            input.prompt or "生成高质量商业海报图像，画面精致，细节丰富。",
            size=size,
        )
        url = await storage.save(png_bytes, "png")
        on_progress(90)
        return NodeOutput(image_url=url)

    ref_bytes = await storage.download(ref_url)

    # 下载遮罩（如果有）
    mask_bytes = None
    if input.mask_url:
        on_progress(20)
        mask_bytes = await storage.download(input.mask_url)

    on_progress(25)

    # 有 mask 走局部重绘
    if mask_bytes:
        png_bytes = await gpt_image.edit_image(
            ref_bytes,
            input.prompt or "在遮罩区域重新生成，保持自然过渡",
            mask_bytes=mask_bytes, size=size,
        )
    elif input.hair_url or input.clothing_url:
        # 图片换装：下载发型/服装参考图，拼接走 generate_character
        hair_bytes = await storage.download(input.hair_url) if input.hair_url else None
        clothing_bytes = await storage.download(input.clothing_url) if input.clothing_url else None
        on_progress(35)
        png_bytes = await gpt_image.generate_character(
            ref_bytes, hair_bytes, input.makeup, clothing_bytes, size=size
        )
    else:
        # 有参考图走 edits
        png_bytes = await gpt_image.edit_image(
            ref_bytes,
            input.prompt or "基于参考图生成高质量图像，保持人物特征，画面精致。",
            size=size,
        )

    url = await storage.save(png_bytes, "png")
    on_progress(90)
    return NodeOutput(image_url=url)
