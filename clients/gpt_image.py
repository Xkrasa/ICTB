"""gpt-image 适配层（同步渠道：llm-api 主 + xhub 兜底）。

阶段一"主播形象加工"：参考图 + 发型/妆容/服装 → 背透 PNG。
用 httpx 直接调 multipart /v1/images/edits（非 openai SDK，因中转响应
格式需可控解析，且响应示例非标准 images 结构）。

模型名由 config.GPT_IMAGE_MODEL 控制，默认 gpt-image-2（中转 default
分组有通道；-all 后缀在 default 分组无通道会 503）。

429 退避重试：中转上游负载饱和时返回 429，按 5s/10s/20s 指数退避重试 3 次。
同步 failover：llm-api 重试仍失败时，若 config.GPT_IMAGE_FAILOVER=true
且 XHUB_API_KEY 已配置，自动切换到 xhub（newapi.pro）再试一轮。
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

# 中转 API 请求体限制：参考图最长边超过此值时等比缩小，避免 429「文件大小超过限制」
MAX_DIM = 2048

_EDIT_SIZES = {"auto", "1024x1024", "1536x1024", "1024x1536"}


def _normalize_edit_size(size: str | None) -> str:
    val = size or config.GPT_IMAGE_SIZE or "1024x1024"
    if val not in _EDIT_SIZES:
        raise ValueError(f"gpt-image edits 不支持 size={val}，仅支持 {sorted(_EDIT_SIZES)}")
    return val


# ───────────────────────── 同步渠道分发 ─────────────────────────

class _ChannelBusinessError(RuntimeError):
    """4xx 业务错误（400/401/403 等），不应切渠道，直接抛给调用方。"""


class _ChannelExhausted(RuntimeError):
    """429/5xx 重试耗尽或网络错误，应切下一个同步渠道。"""


def _channels() -> list[tuple[str, str, str]]:
    """返回启用的同步渠道列表 [(name, base_url, api_key), ...]。

    顺序即优先级：llm-api 优先；failover 开启且 xhub key 配置时追加 xhub。
    """
    channels = [("llm-api", config.OPENAI_BASE_URL, config.OPENAI_API_KEY)]
    if config.GPT_IMAGE_FAILOVER and config.XHUB_API_KEY:
        channels.append(("xhub", config.XHUB_BASE_URL, config.XHUB_API_KEY))
    return channels


async def _post_edits_with_retry(
    base_url: str, api_key: str, form_data: dict, files: dict
) -> bytes:
    """对单个渠道执行 429 退避重试 + raise_for_status，返回图像 bytes。"""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    last_err: Exception | None = None
    async with httpx.AsyncClient(timeout=config.GPT_IMAGE_TIMEOUT) as client:
        for attempt, backoff in enumerate([0] + _RETRY_BACKOFFS):
            if backoff:
                await asyncio.sleep(backoff)
            try:
                resp = await client.post(
                    f"{base_url}/images/edits",
                    headers=headers,
                    data=form_data,
                    files=files,
                )
                if resp.status_code in _RETRY_STATUSES and attempt < len(_RETRY_BACKOFFS):
                    last_err = _ChannelExhausted(
                        f"gpt-image HTTP {resp.status_code}（重试 {attempt+1}/{len(_RETRY_BACKOFFS)}）: {resp.text[:200]}"
                    )
                    continue
                if resp.status_code in (401, 403):
                    # 认证/权限错误：当前渠道不可用，切下一个渠道
                    raise _ChannelExhausted(
                        f"gpt-image HTTP {resp.status_code}: {resp.text}"
                    )
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    # 业务错误（参数、文件格式等）：不重试，不切渠道
                    raise _ChannelBusinessError(
                        f"gpt-image HTTP {resp.status_code}: {resp.text}"
                    )
                resp.raise_for_status()
                payload = resp.json()
                return await _extract_image_bytes(payload)
            except httpx.HTTPStatusError as e:
                # 5xx：切渠道
                raise _ChannelExhausted(
                    f"gpt-image HTTP {e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.HTTPError as e:
                # 网络错误：重试或切渠道
                if attempt < len(_RETRY_BACKOFFS):
                    last_err = _ChannelExhausted(f"gpt-image 请求失败: {e}")
                    continue
                raise _ChannelExhausted(f"gpt-image 请求失败: {e}") from e
    raise last_err or _ChannelExhausted("gpt-image 重试耗尽")


async def _dispatch_edits(form_data: dict, files: dict) -> bytes:
    """按渠道优先级依次尝试，429/5xx/网络错误自动切下一个同步渠道；4xx 直接抛。"""
    last_err: Exception | None = None
    for name, base_url, api_key in _channels():
        try:
            return await _post_edits_with_retry(base_url, api_key, form_data, files)
        except _ChannelBusinessError:
            # 4xx 业务错误：不切渠道
            raise
        except _ChannelExhausted as e:
            last_err = e
            # 切下一个渠道
            continue
    raise RuntimeError(
        f"所有同步渠道均失败（llm-api + xhub）。最后错误: {last_err}"
    )


async def generate_character(
    reference_image_bytes: bytes,
    hair_image_bytes: bytes | None = None,
    makeup: str = "",
    clothing_image_bytes: bytes | None = None,
    size: str | None = None,
) -> bytes:
    """参考图 + 发型/服装参考图 → 背透 PNG bytes（可直接 storage.save）。

    将人物参考图与发型/服装参考图横向拼接为一张图（等高对齐 + 图间留白），
    配合 prompt 描述布局，走 images/edits 接口。未提供的参考图跳过。

    Raises:
        RuntimeError: API 调用失败或响应无可用图像数据。
    """
    parts = [("人物参考图", _load_rgb_image(reference_image_bytes))]
    if hair_image_bytes:
        parts.append(("发型参考图", _load_rgb_image(hair_image_bytes)))
    if clothing_image_bytes:
        parts.append(("服装参考图", _load_rgb_image(clothing_image_bytes)))

    combined = _hconcat(parts, gap=24)
    out = BytesIO()
    combined.save(out, format="PNG", optimize=True)
    combined_bytes = out.getvalue()

    prompt = _build_image_prompt([p[0] for p in parts], makeup)

    form_data = {
        "model": config.GPT_IMAGE_MODEL,
        "prompt": prompt,
        "size": _normalize_edit_size(size),
        "quality": config.GPT_IMAGE_QUALITY,
        "background": "transparent",
        "n": "1",
    }
    if config.GPT_IMAGE_THINKING:
        form_data["thinking"] = config.GPT_IMAGE_THINKING

    files = {"image": ("reference.png", combined_bytes, "image/png")}
    return await _dispatch_edits(form_data, files)


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
        async with httpx.AsyncClient(timeout=config.GPT_IMAGE_TIMEOUT) as c:
            r = await c.get(url)
            r.raise_for_status()
            return r.content
    raise RuntimeError(f"gpt-image 响应无 b64_json 也无 url: {item}")


def _load_rgb_image(image_bytes: bytes) -> Image.Image:
    """加载图片为 RGB PIL Image（白底合成 + 最长边 MAX_DIM 压缩）。

    免疫所有输入模式（P 调色盘、LA 灰度透明、L 灰度等），确保 gpt-image
    的 images.edit 接口不因 alpha 通道报错。强制 convert("RGBA") 后
    split()[3] 必定存在且合法。超过 MAX_DIM 的图等比缩小（LANCZOS）。
    """
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")
    w, h = img.size
    longest = max(w, h)
    if longest > MAX_DIM:
        scale = MAX_DIM / longest
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3])
    return bg


def _ensure_rgb(image_bytes: bytes) -> bytes:
    """预处理参考图：转 RGB + 尺寸压缩，返回 PNG bytes（edit_image 路径使用）。"""
    img = _load_rgb_image(image_bytes)
    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _hconcat(parts: list[tuple[str, Image.Image]], gap: int = 24) -> Image.Image:
    """横向拼接多张图，等高对齐（按最高图高度等比缩放），图间留白，整体限制 MAX_DIM。"""
    target_h = max(p[1].height for p in parts)
    scaled = []
    for name, img in parts:
        if img.height != target_h:
            scale = target_h / img.height
            img = img.resize((max(1, int(img.width * scale)), target_h), Image.LANCZOS)
        scaled.append((name, img))
    total_w = sum(p[1].width for p in scaled) + gap * (len(scaled) - 1)
    canvas = Image.new("RGB", (total_w, target_h), (255, 255, 255))
    x = 0
    for _, img in scaled:
        canvas.paste(img, (x, 0))
        x += img.width + gap
    longest = max(canvas.size)
    if longest > MAX_DIM:
        scale = MAX_DIM / longest
        canvas = canvas.resize(
            (max(1, int(canvas.width * scale)), max(1, int(canvas.height * scale))),
            Image.LANCZOS,
        )
    return canvas


def _build_image_prompt(part_names: list[str], makeup: str) -> str:
    """拼装基于参考图布局的换装 prompt（中文，gpt-image 原生支持 CJK）。"""
    layout = "从左到右依次为：" + "、".join(part_names) + "。"
    return (
        f"参考图布局说明：{layout}\n"
        "请基于「人物参考图」保持人物五官与身份完全一致（必须是同一个人），"
        "应用「发型参考图」中的发型，换上「服装参考图」中的服装。\n"
        f"妆容要求：{makeup or '自然清透'}。\n"
        "半身/全身站立姿态，自然光线，质感细腻。\n"
        "纯透明背景（用于后续海报合成）。\n"
        "高质量，画面中不要出现任何文字与水印。"
    )


async def edit_image(
    reference_image_bytes: bytes,
    prompt: str,
    mask_bytes: bytes | None = None,
    size: str | None = None,
) -> bytes:
    """通用图像编辑：参考图 + prompt → PNG bytes。

    Args:
        reference_image_bytes: 参考图原始 bytes
        prompt: 编辑指令
        mask_bytes: 可选遮罩 PNG bytes。透明区域（alpha=0）表示需要重绘，
                    非透明区域保持不变。传入时执行 inpainting 局部重绘。

    与 generate_character 共用 _ensure_rgb / 429 重试 / 同步 failover。
    """
    rgb_bytes = _ensure_rgb(reference_image_bytes)

    if mask_bytes:
        full_prompt = prompt + "\n高质量，画面中不要出现任何文字与水印。"
    else:
        full_prompt = prompt + "\n纯透明背景。高质量，画面中不要出现任何文字与水印。"

    form_data = {
        "model": config.GPT_IMAGE_MODEL,
        "prompt": full_prompt,
        "size": _normalize_edit_size(size),
        "quality": config.GPT_IMAGE_QUALITY,
        "n": "1",
    }
    if not mask_bytes:
        form_data["background"] = "transparent"
    if config.GPT_IMAGE_THINKING:
        form_data["thinking"] = config.GPT_IMAGE_THINKING

    files = {"image": ("reference.png", rgb_bytes, "image/png")}
    if mask_bytes:
        files["mask"] = ("mask.png", mask_bytes, "image/png")

    return await _dispatch_edits(form_data, files)
