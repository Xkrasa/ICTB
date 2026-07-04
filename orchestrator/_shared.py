"""orchestrator 共享工具：错误分类、图片尺寸记录、并发闸、后台任务集合。"""
import asyncio
import logging

from storage import storage
from .registry import registry

logger = logging.getLogger("orchestrator")

# 标准化错误码
ERROR_CODES = {
    "TIMEOUT": {"code": "E001", "label": "超时"},
    "API_ERROR": {"code": "E002", "label": "API调用失败"},
    "CONTENT_AUDIT": {"code": "E003", "label": "内容安全审查未通过"},
    "NO_UPSTREAM": {"code": "E004", "label": "缺少上游输入"},
    "INVALID_PARAM": {"code": "E005", "label": "参数无效"},
    "MODEL_ERROR": {"code": "E006", "label": "模型错误"},
    "UPLOAD_ERROR": {"code": "E007", "label": "上传失败"},
    "UNKNOWN": {"code": "E999", "label": "未知错误"},
}

def classify_error(error_msg: str) -> dict:
    """根据错误信息分类返回标准化错误码"""
    msg = str(error_msg).lower()
    if "timeout" in msg or "timed out" in msg:
        return ERROR_CODES["TIMEOUT"]
    if "content security" in msg or "内容安全" in msg or "errorcode=1501" in msg or "audit" in msg.lower():
        return ERROR_CODES["CONTENT_AUDIT"]
    if "no upstream" in msg or "缺少上游" in msg or "no image" in msg or "未检测到人脸" in msg:
        return ERROR_CODES["NO_UPSTREAM"]
    if "invalid" in msg or "参数" in msg or "不支持的" in msg:
        return ERROR_CODES["INVALID_PARAM"]
    if "api" in msg or "401" in msg or "403" in msg or "429" in msg or "500" in msg:
        return ERROR_CODES["API_ERROR"]
    if "model" in msg:
        return ERROR_CODES["MODEL_ERROR"]
    if "upload" in msg or "上传" in msg:
        return ERROR_CODES["UPLOAD_ERROR"]
    return ERROR_CODES["UNKNOWN"]


async def _record_image_size(canvas_id: str, node_id: str, image_url: str) -> None:
    """读取图片实际尺寸并写入 registry（用于前端显示和 size 参数验证）"""
    try:
        from PIL import Image as PILImage
        path = storage.url_to_path(image_url)
        loop = asyncio.get_running_loop()
        def _read_size():
            with PILImage.open(path) as img:
                return img.size  # (width, height)
        width, height = await loop.run_in_executor(None, _read_size)
        registry.update(f"{canvas_id}:{node_id}", width=width, height=height)
    except Exception:
        pass  # 尺寸读取失败不影响主流程


# 并发闸：最多 3 个节点同时执行
SEM = asyncio.Semaphore(3)

# 后台任务引用集合，防止被 GC 回收
_background_tasks: set = set()
