"""Mock 端到端批准模式闭环测试。

验证链路：image_input → gpt_image → seedance_video
- gpt_image 成功后进入 awaiting_approval
- 用户批准后变为 success，触发 seedance_video
- seedance_video 成功后进入 awaiting_approval
- 批准后最终 success

不调用真实 AI API，通过 monkeypatch 替换 executor。
"""
import asyncio
import io
import os
import time
from pathlib import Path

# 确保从当前目录导入
os.chdir(Path(__file__).parent)

import orchestrator
from PIL import Image


def _make_image_bytes(width=512, height=512):
    img = Image.new("RGB", (width, height), (200, 180, 160))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _mock_gpt_image(canvas_id: str, node_id: str, params: dict) -> None:
    """模拟 gpt_image 执行：产出一张灰色占位图。"""
    await asyncio.sleep(0.1)
    from storage import storage
    img_bytes = _make_image_bytes(512, 512)
    url = await storage.save(img_bytes, ext="png")
    orchestrator.registry.update(
        f"{canvas_id}:{node_id}",
        image_url=url,
        _width=512,
        _height=512,
    )


async def _mock_seedance_video(canvas_id: str, node_id: str, params: dict) -> None:
    """模拟 seedance_video 执行：产出视频 URL 占位。"""
    await asyncio.sleep(0.1)
    orchestrator.registry.update(
        f"{canvas_id}:{node_id}",
        video_url=f"/assets/mock_{canvas_id}_{node_id}.mp4",
    )


async def poll_status(canvas_id: str, node_id: str, timeout: float = 10.0):
    key = f"{canvas_id}:{node_id}"
    start = time.time()
    while time.time() - start < timeout:
        rec = orchestrator.registry.get(key)
        if rec and rec["status"] in ("success", "failed", "blocked", "awaiting_approval"):
            return rec
        await asyncio.sleep(0.1)
    return orchestrator.registry.get(key)


async def main():
    canvas_id = "mock_approval_chain"

    nodes = [
        {"id": "img", "type": "image_input", "x": 100, "y": 100, "data": {}},
        {"id": "gpt", "type": "gpt_image", "x": 400, "y": 100, "data": {"prompt": "mock"}},
        {"id": "vid", "type": "seedance_video", "x": 700, "y": 100, "data": {"prompt": "mock video"}},
    ]
    connections = [
        {"id": "c1", "from": "img", "fromField": "image", "to": "gpt", "toField": "image1"},
        {"id": "c2", "from": "gpt", "fromField": "image", "to": "vid", "toField": "first_frame"},
    ]

    # 先上传一张模拟图给 image_input
    from storage import storage
    img_bytes = _make_image_bytes()
    img_url = await storage.save(img_bytes, ext="png")
    nodes[0]["data"]["image_url"] = img_url

    # Monkeypatch executor
    orig_executors = {
        "gpt_image": orchestrator._NODE_EXECUTORS["gpt_image"],
        "seedance_video": orchestrator._NODE_EXECUTORS["seedance_video"],
    }
    orchestrator._NODE_EXECUTORS["gpt_image"] = _mock_gpt_image
    orchestrator._NODE_EXECUTORS["seedance_video"] = _mock_seedance_video

    try:
        print("=== Mock 批准模式闭环测试 ===")
        print(f"画布: {canvas_id}")

        # 运行画布，开启批准模式
        statuses = orchestrator.execute_canvas(
            canvas_id=canvas_id,
            nodes=nodes,
            connections=connections,
            approval_mode=True,
        )
        print(f"execute_canvas 返回: {statuses}")
        await asyncio.sleep(0.5)

        # 等待 gpt 进入 awaiting_approval
        rec = await poll_status(canvas_id, "gpt", timeout=10.0)
        assert rec, "gpt 节点没有记录"
        assert rec["status"] == "awaiting_approval", f"gpt 应进入 awaiting_approval，实际 {rec['status']}"
        print("✅ gpt_image 进入 awaiting_approval")

        # 批准 gpt
        result = orchestrator.approve_node(canvas_id, "gpt")
        assert result["status"] == "success"
        print("✅ gpt_image 已批准")

        # 等待 vid 进入 awaiting_approval
        rec = await poll_status(canvas_id, "vid", timeout=15.0)
        assert rec, "vid 节点没有记录"
        print(f"vid 当前状态: {rec['status']}, error: {rec.get('error')}")
        assert rec["status"] == "awaiting_approval", f"vid 应进入 awaiting_approval，实际 {rec['status']}"
        print("✅ seedance_video 进入 awaiting_approval")

        # 批准 vid
        result = orchestrator.approve_node(canvas_id, "vid")
        assert result["status"] == "success"
        print("✅ seedance_video 已批准")

        # 最终检查
        gpt_rec = orchestrator.registry.get(f"{canvas_id}:gpt")
        vid_rec = orchestrator.registry.get(f"{canvas_id}:vid")
        assert gpt_rec["status"] == "success", f"gpt 最终状态应为 success: {gpt_rec['status']}"
        assert vid_rec["status"] == "success", f"vid 最终状态应为 success: {vid_rec['status']}"
        assert vid_rec.get("video_url"), "vid 应有 video_url"
        print("✅ 完整 mock 批准模式闭环通过")
        print(f"   gpt image_url: {gpt_rec.get('image_url')}")
        print(f"   vid video_url: {vid_rec.get('video_url')}")

    finally:
        # 恢复 executor
        orchestrator._NODE_EXECUTORS.update(orig_executors)
        # 清理上下文
        orchestrator._canvas_contexts.pop(canvas_id, None)


if __name__ == "__main__":
    asyncio.run(main())
