"""gpt-image 适配层（第三方中转 https://llm-api.net/v1）。

阶段一"主播形象加工"：参考图 + 发型/妆容/服装 → 背透 PNG。
用 httpx 直接调 multipart /v1/images/edits（非 openai SDK，因中转响应
格式需可控解析，且响应示例非标准 images 结构）。

模型名由 config.GPT_IMAGE_MODEL 控制，默认 gpt-image-2（中转 default
分组有通道；-all 后缀在 default 分组无通道会 503）。

429 退避重试：中转上游负载饱和时返回 429，按 5s/10s/20s 指数退避重试 3 次。
"""
import asyncio
import base64
from io import BytesIO

import httpx
from PIL import Image

import config

# 429 退避重试配置（中转上游负载饱和时的标准应对）
_RETRY_STATUSES = {429, 502, 503, 504}
_RETRY_BACKOFFS = [5, 10, 20]  # 指数退避秒数，最多 3 次


async def generate_character(
    reference_image_bytes: bytes,
    hair: str,
    makeup: str,
    clothing: str,
) -> bytes:
    """参考图 + 换装描述 → 背透 PNG bytes（可直接 storage.save）。

    Raises:
        RuntimeError: API 调用失败或响应无可用图像数据。
    """
    rgb_bytes = _ensure_rgb(reference_image_bytes)
    prompt = _build_prompt(hair, makeup, clothing)

    form_data = {
        "model": config.GPT_IMAGE_MODEL,
        "prompt": prompt,
        "size": config.GPT_IMAGE_SIZE,
        "quality": config.GPT_IMAGE_QUALITY,
        "background": "transparent",
        "n": "1",
    }
    # thinking 参数中转文档未列，仅在配置非空时透传
    if config.GPT_IMAGE_THINKING:
        form_data["thinking"] = config.GPT_IMAGE_THINKING

    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Accept": "application/json",
    }

    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=config.GPT_IMAGE_TIMEOUT) as client:
        for attempt, backoff in enumerate([0] + _RETRY_BACKOFFS):
            if backoff:
                await asyncio.sleep(backoff)
            try:
                resp = await client.post(
                    f"{config.OPENAI_BASE_URL}/images/edits",
                    headers=headers,
                    data=form_data,
                    files={"image": ("reference.png", rgb_bytes, "image/png")},
                )
                if resp.status_code in _RETRY_STATUSES and attempt < len(_RETRY_BACKOFFS):
                    last_err = RuntimeError(
                        f"gpt-image HTTP {resp.status_code}（重试 {attempt+1}/{len(_RETRY_BACKOFFS)}）: {resp.text[:200]}"
                    )
                    continue
                resp.raise_for_status()
                payload = resp.json()
                return await _extract_image_bytes(payload)
            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"gpt-image HTTP {e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.HTTPError as e:
                if attempt < len(_RETRY_BACKOFFS):
                    last_err = e
                    continue
                raise RuntimeError(f"gpt-image 请求失败: {e}") from e

    raise RuntimeError(f"gpt-image 重试 {len(_RETRY_BACKOFFS)} 次仍失败: {last_err}")


async def _extract_image_bytes(payload: dict) -> bytes:
    """从响应解析图像 bytes：优先 data[0].b64_json，降级 data[0].url（下载本地化）。"""
    items = payload.get("data") or []
    if not items:
        raise RuntimeError(f"gpt-image 返回空 data: {payload}")
    item = items[0]
    b64 = item.get("b64_json")
    if b64:
        return base64.b64decode(b64)
    url = item.get("url")
    if url:
        # URL 60 分钟过期，下载本地化
        async with httpx.AsyncClient(timeout=config.GPT_IMAGE_TIMEOUT) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content
    raise RuntimeError(f"gpt-image 响应无 b64_json 也无 url: {item}")


def _ensure_rgb(image_bytes: bytes) -> bytes:
    """预处理参考图：强制转 RGBA 再白底合成 RGB。

    免疫所有输入模式（P 调色盘、LA 灰度透明、L 灰度等），确保 gpt-image
    的 images.edit 接口不因 alpha 通道报错。强制 convert("RGBA") 后
    split()[3] 必定存在且合法。
    """
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3])
    out = BytesIO()
    bg.save(out, format="PNG")
    return out.getvalue()


def _build_prompt(hair: str, makeup: str, clothing: str) -> str:
    """拼装换装 prompt（中文，gpt-image 原生支持 CJK）。"""
    return (
        "保持人物五官与参考图完全一致（必须是同一个人）。\n"
        f"换装要求：发型={hair}，妆容={makeup}，服装={clothing}。\n"
        "半身/全身站立姿态，自然光线，质感细腻。\n"
        "纯透明背景（用于后续海报合成）。\n"
        "高质量，画面中不要出现任何文字与水印。"
    )


async def edit_image(reference_image_bytes: bytes, prompt: str) -> bytes:
    """通用图像编辑：参考图 + 任意 prompt → PNG bytes。

    与 generate_character 共用 _ensure_rgb / 429 重试 / _extract_image_bytes，
    区别仅在于 prompt 由调用方完全自定义。
    """
    rgb_bytes = _ensure_rgb(reference_image_bytes)
    full_prompt = prompt + "\n纯透明背景。高质量，画面中不要出现任何文字与水印。"

    form_data = {
        "model": config.GPT_IMAGE_MODEL,
        "prompt": full_prompt,
        "size": config.GPT_IMAGE_SIZE,
        "quality": config.GPT_IMAGE_QUALITY,
        "background": "transparent",
        "n": "1",
    }
    if config.GPT_IMAGE_THINKING:
        form_data["thinking"] = config.GPT_IMAGE_THINKING

    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Accept": "application/json",
    }

    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=config.GPT_IMAGE_TIMEOUT) as client:
        for attempt, backoff in enumerate([0] + _RETRY_BACKOFFS):
            if backoff:
                await asyncio.sleep(backoff)
            try:
                resp = await client.post(
                    f"{config.OPENAI_BASE_URL}/images/edits",
                    headers=headers,
                    data=form_data,
                    files={"image": ("reference.png", rgb_bytes, "image/png")},
                )
                if resp.status_code in _RETRY_STATUSES and attempt < len(_RETRY_BACKOFFS):
                    last_err = RuntimeError(
                        f"gpt-image HTTP {resp.status_code}（重试 {attempt+1}/{len(_RETRY_BACKOFFS)}）: {resp.text[:200]}"
                    )
                    continue
                resp.raise_for_status()
                payload = resp.json()
                return await _extract_image_bytes(payload)
            except httpx.HTTPStatusError as e:
                raise RuntimeError(
                    f"gpt-image HTTP {e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.HTTPError as e:
                if attempt < len(_RETRY_BACKOFFS):
                    last_err = e
                    continue
                raise RuntimeError(f"gpt-image 请求失败: {e}") from e

    raise RuntimeError(f"gpt-image 重试 {len(_RETRY_BACKOFFS)} 次仍失败: {last_err}")
