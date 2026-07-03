"""节点类型定义：类型化输入/输出 + 端口声明。

深化目标：把 orchestrator 里执行器的 `params: dict` 浅接口替换为类型化
NodeInput dataclass。PortResolver 按 NODE_PORTS 把上游注入 + node.data
用户配置归一化为类型化输入，执行器只消费强类型字段。

NODE_PORTS 扩展了 `overridable` 字段，消除原 orchestrator.py 里两处重复的
_OVERRIDABLE 集合（候选5并入）。
"""
from dataclasses import dataclass, fields
from typing import Callable


# ───────────────────────── 节点输出（统一） ─────────────────────────

@dataclass
class NodeOutput:
    """执行器产出。执行器填对应字段，引擎写回 registry。"""
    image_url: str | None = None
    video_url: str | None = None
    mask_url: str | None = None


# ───────────────────────── 节点输入（每类型一个） ─────────────────────────

@dataclass
class ImageInputInput:
    """image_input：用户上传的图片 URL（非端口注入）。"""
    image_url: str = ""


@dataclass
class GptImageInput:
    """gpt_image：参考图 + prompt → PNG。端口字段 image1/image2 + 用户配置。"""
    # 端口输入（PortResolver 按 NODE_PORTS 注入）
    image1: str | None = None        # 端口 "image1" · 主体图
    image2: str | None = None        # 端口 "image2" · 参考图
    # 用户配置（node.data）
    prompt: str = ""
    model: str = "gpt-image-2"
    size: str | None = None
    aspect_ratio: str = "16:9"
    resolution: str = "1024x1024"
    hair_url: str | None = None
    makeup: str = ""
    clothing_url: str | None = None
    mask_url: str | None = None
    # nano_banana_2 额外参考图（非端口，用户配置）
    image3_url: str | None = None
    image4_url: str | None = None


@dataclass
class RemoveBgInput:
    """remove_bg：端口 "image" → 透明 PNG。"""
    image: str | None = None


@dataclass
class MaskEditInput:
    """mask_edit：端口 "image" + 遮罩模式 → 原图 + mask。"""
    image: str | None = None         # 端口 "image"
    mask_url: str | None = None
    mask_mode: str = "manual"        # auto_face / auto_full / manual
    expand: float = 0.25
    face_index: int = -1
    detect_method: str = "auto"
    mask_value: int = 255


@dataclass
class SeedanceInput:
    """seedance_video：端口 "first_frame"/"last_frame" + prompt → 视频。"""
    first_frame: str | None = None   # 端口 "first_frame"
    last_frame: str | None = None    # 端口 "last_frame"
    prompt: str = ""
    duration: str = "8"
    aspect_ratio: str = "9:16"
    channel: str = "official"
    resolution: str = "480p"


# ───────────────────────── 端口声明（扩展 overridable） ─────────────────────────

NODE_PORTS: dict[str, dict] = {
    "image_input": {
        "inputs": [],
        "outputs": [{"name": "image", "type": "IMAGE", "label": "图片"}],
        "overridable": False,
    },
    "gpt_image": {
        "inputs": [
            {"name": "image1", "type": "IMAGE", "label": "图1 · 主体"},
            {"name": "image2", "type": "IMAGE", "label": "图2 · 参考"},
            {"name": "prompt", "type": "TEXT", "label": "提示词"},
        ],
        "outputs": [{"name": "image", "type": "IMAGE", "label": "生成图"}],
        "overridable": True,
    },
    "remove_bg": {
        "inputs": [{"name": "image", "type": "IMAGE", "label": "图片"}],
        "outputs": [{"name": "image", "type": "IMAGE", "label": "透明图"}],
        "overridable": True,
    },
    "mask_edit": {
        "inputs": [{"name": "image", "type": "IMAGE", "label": "待编辑图"}],
        "outputs": [
            {"name": "image", "type": "IMAGE", "label": "原图"},
            {"name": "mask", "type": "MASK", "label": "遮罩"},
        ],
        "overridable": True,
    },
    "seedance_video": {
        "inputs": [
            {"name": "first_frame", "type": "IMAGE", "label": "首帧"},
            {"name": "last_frame", "type": "IMAGE", "label": "尾帧（可选）"},
            {"name": "prompt", "type": "TEXT", "label": "视频描述"},
        ],
        "outputs": [{"name": "video", "type": "VIDEO", "label": "视频"}],
        "overridable": True,
    },
}

# 产物键 → 端口名映射（PortResolver 按 fromField 取上游产物时用）
_OUTPUT_FIELD_MAP = {
    "image_url": "image",
    "video_url": "video",
    "mask_url": "mask",
}

# 端口名 → 产物键（反向映射）
_PORT_TO_ASSET = {v: k for k, v in _OUTPUT_FIELD_MAP.items()}

# node_type → NodeInput dataclass
NODE_INPUT_TYPES: dict[str, type] = {
    "image_input": ImageInputInput,
    "gpt_image": GptImageInput,
    "remove_bg": RemoveBgInput,
    "mask_edit": MaskEditInput,
    "seedance_video": SeedanceInput,
}


def build_input(node_type: str, data: dict) -> object:
    """从归一化后的 data dict 构造类型化 NodeInput。

    只取 dataclass 定义的字段，忽略多余键。PortResolver 调用此函数。
    """
    cls = NODE_INPUT_TYPES.get(node_type)
    if cls is None:
        raise ValueError(f"未知节点类型: {node_type}")
    valid_keys = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in data.items() if k in valid_keys and v is not None}
    return cls(**filtered)


def is_overridable(node_type: str) -> bool:
    """该节点类型是否允许上游产物覆盖已有字段（替代原 _OVERRIDABLE 集合）。"""
    return NODE_PORTS.get(node_type, {}).get("overridable", False)
