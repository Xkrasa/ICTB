"""遮罩生成服务：基于人脸检测自动生成遮罩。

提供两种自动模式：
- auto_face：检测人脸并生成覆盖人脸区域的二值遮罩
- auto_full：生成全图保留遮罩（兜底方案）

依赖：Pillow、numpy、opencv-python（推荐）
"""
import io
import logging
import os
from pathlib import Path

import numpy as np
from PIL import Image

# 抑制 OpenCV DNN 在新 graph engine 下的 warning（YuNet 仍可正常工作）
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")

logger = logging.getLogger("mask_service")


def _pil_to_numpy(img: Image.Image) -> np.ndarray:
    """PIL Image → RGB numpy array（uint8）"""
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.array(img)


def _import_cv2():
    """懒加载 cv2，避免启动时强依赖。"""
    try:
        import cv2
        return cv2
    except ImportError as e:
        raise ValueError("opencv-python 未安装，无法生成人脸遮罩") from e


def _load_haar_classifier():
    """加载 OpenCV 自带的 Haar 人脸级联分类器。"""
    cv2 = _import_cv2()
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not cascade_path.exists():
        # 尝试其他 frontalface 变体
        for name in ("haarcascade_frontalface_alt2.xml", "haarcascade_frontalface_alt.xml"):
            cascade_path = Path(cv2.data.haarcascades) / name
            if cascade_path.exists():
                break
    if not cascade_path.exists():
        raise ValueError("未找到 OpenCV Haar 人脸检测模型文件")
    return cv2.CascadeClassifier(str(cascade_path))


def generate_full_mask(image_bytes: bytes) -> bytes:
    """生成与输入图同尺寸的白色遮罩（全保留）。"""
    with Image.open(io.BytesIO(image_bytes)) as img:
        width, height = img.size
        mask = Image.new("L", (width, height), 255)
        buf = io.BytesIO()
        mask.save(buf, format="PNG")
        return buf.getvalue()


def _detect_faces_yunet(cv2, rgb: np.ndarray, model_path: str | None = None):
    """使用 OpenCV YuNet (FaceDetectorYN) 检测人脸。

    Returns:
        list[(x1, y1, x2, y2)] 的人脸 bbox 列表
    """
    if model_path is None:
        model_path = str(Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx")
    detector = cv2.FaceDetectorYN_create(model_path, "", (0, 0))
    detector.setInputSize((rgb.shape[1], rgb.shape[0]))
    _, faces = detector.detect(rgb)
    if faces is None or len(faces) == 0:
        return []
    bboxes = []
    for f in faces:
        x, y, w, h, conf = f[:5]
        if conf < 0.5:
            continue
        bboxes.append((int(x), int(y), int(x + w), int(y + h)))
    return bboxes


def detect_face_mask(
    image_bytes: bytes,
    expand: float = 0.25,
    method: str = "auto",
    smooth: bool = True,
    face_index: int = -1,
    mask_value: int = 255,
) -> bytes:
    """检测人脸并生成人脸区域二值/灰度遮罩。

    Args:
        image_bytes: 输入图片 bytes
        expand: 人脸 bbox 向外扩展的比例（0.0 ~ 1.0），用于覆盖发际线/下巴
        method: 检测方法，支持
            - "auto"（默认）：级联 YuNet → Haar，最大化召回率
            - "opencv_yunet"：高精度，适合真实照片
            - "opencv_haar"：无额外依赖，适合简单场景
        smooth: 是否对遮罩边缘做羽化，使过渡更自然
        face_index: 指定使用第几个人脸，-1 表示全部，0/1/2... 表示按面积从大到小取第 N 个
        mask_value: 遮罩区域像素值，默认 255（纯白二值），可设为 128 等生成灰色遮罩

    Returns:
        PNG bytes，黑底遮罩脸（遮罩区域为 mask_value）

    Raises:
        ValueError: 未检测到人脸、依赖缺失或 face_index 超出范围
    """
    if method not in ("auto", "opencv_haar", "opencv_yunet"):
        raise ValueError(f"不支持的检测方法: {method}，支持 auto / opencv_haar / opencv_yunet")

    cv2 = _import_cv2()
    with Image.open(io.BytesIO(image_bytes)) as img:
        width, height = img.size
        rgb = _pil_to_numpy(img)

    bboxes: list[tuple[int, int, int, int]] = []

    if method in ("auto", "opencv_yunet"):
        bboxes = _detect_faces_yunet(cv2, rgb)

    if len(bboxes) == 0 and method in ("auto", "opencv_haar"):
        # Haar 需要灰度图
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        classifier = _load_haar_classifier()
        raw = classifier.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(max(width // 20, 24), max(height // 20, 24)),
        )
        bboxes = [(int(x), int(y), int(x + w), int(y + h)) for (x, y, w, h) in raw]

    if len(bboxes) == 0:
        raise ValueError("未检测到人脸，无法生成人脸遮罩")


    # 按面积从大到小排序，便于 face_index 选择
    bboxes = sorted(bboxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)

    if face_index != -1:
        if face_index < 0 or face_index >= len(bboxes):
            raise ValueError(f"face_index={face_index} 超出范围，仅检测到 {len(bboxes)} 个人脸")
        selected = [bboxes[face_index]]
    else:
        selected = bboxes

    # 生成人脸椭圆遮罩（覆盖全脸）
    mask = np.zeros((height, width), dtype=np.uint8)
    for (x1, y1, x2, y2) in selected:
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        # 椭圆：宽度用 bbox 宽，高度用 bbox 高，略作比例修正使更符合人脸
        rx = int((x2 - x1) // 2)
        ry = int((y2 - y1) // 2)
        cv2.ellipse(mask, (cx, cy), (rx, ry), 0, 0, 360, mask_value, -1)

    # 按 bbox 扩展，确保额头/下巴/发际线也被覆盖
    if expand > 0:
        # 基于选中人脸平均尺寸计算膨胀核，expand 比例越大覆盖越多
        avg_w = sum(x2 - x1 for (x1, y1, x2, y2) in selected) / len(selected)
        avg_h = sum(y2 - y1 for (x1, y1, x2, y2) in selected) / len(selected)
        kernel_size = max(1, int(min(avg_w, avg_h) * expand))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
        mask = cv2.dilate(mask, kernel, iterations=1)
        # 膨胀后像素值可能被稀释，重新归一化到 mask_value
        if mask_value < 255:
            mask = np.clip(mask * (mask_value / 255.0), 0, mask_value).astype(np.uint8)

    # 边缘羽化：二值模式做阈值；灰度模式保持渐变
    if smooth:
        mask = cv2.GaussianBlur(mask, (15, 15), 0)
        if mask_value == 255:
            _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
        else:
            # 灰度遮罩：边缘保留灰度渐变，但主体区域提升到 mask_value
            mask = np.clip(mask * 1.2, 0, mask_value).astype(np.uint8)

    pil_mask = Image.fromarray(mask, mode="L")
    buf = io.BytesIO()
    pil_mask.save(buf, format="PNG")
    return buf.getvalue()
