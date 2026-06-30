"""端到端测试套件：覆盖所有核心 API 路由。

测试范围：
- 健康检查
- 文件上传（正常 + 异常）
- 画布 CRUD + 运行
- 主播 CRUD
- 模板 CRUD
- 批量编排（run/list/adopt/retry/video）
- 错误处理 (404/400/413)
- Phase 1 兼容路由

运行方式：python -m pytest tests/test_e2e.py -v --tb=short
前提：服务已在 127.0.0.1:8001 运行
"""
import io
import json
import time
import uuid

import httpx
import pytest

BASE = "http://127.0.0.1:8001"
# 允许 API_KEY 为空（本地开发），若 .env 设了 API_KEY 则需通过环境变量传入
API_KEY = __import__("os").getenv("API_KEY", "")


def _headers():
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _post(path, **kw):
    return httpx.post(f"{BASE}{path}", headers=_headers(), **kw)


def _get(path, **kw):
    return httpx.get(f"{BASE}{path}", headers=_headers(), **kw)


def _delete(path, **kw):
    return httpx.delete(f"{BASE}{path}", headers=_headers(), **kw)


# ───────────────────────── 工具函数 ─────────────────────────

def _dummy_png():
    """生成最小有效 PNG 字节（1x1 红色像素）"""
    import struct, zlib
    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw = b"\x00\x00\x00\xff\xff\x00\x00"  # 红色 1x1 带 alpha
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _upload_png():
    """上传一张测试 PNG 并返回 URL"""
    r = _post("/api/assets/upload", files={"file": ("test.png", io.BytesIO(_dummy_png()), "image/png")})
    assert r.status_code == 200, f"upload failed: {r.text}"
    return r.json()["url"]


def _create_streamer(name="测试主播", image_url=None):
    if image_url is None:
        image_url = _upload_png()
    r = _post("/api/streamers", json={"name": name, "source_image_url": image_url, "tag": "test"})
    assert r.status_code == 200, f"create streamer failed: {r.text}"
    return r.json()


def _create_template(name="测试模板", image_url=None, nodes=None, connections=None):
    if image_url is None:
        image_url = _upload_png()
    if nodes is None:
        nodes = [
            {"id": "img1", "type": "image_input", "x": 100, "y": 100, "data": {"image_url": image_url}},
            {"id": "gen1", "type": "gpt_image", "x": 400, "y": 100, "data": {"prompt": "test prompt", "model": "gpt-image-2", "resolution": "1024x1024", "aspect_ratio": "16:9"}},
        ]
    if connections is None:
        connections = [{"id": "c1", "from": "img1", "to": "gen1"}]
    r = _post("/api/templates", json={"name": name, "category": "test", "nodes": nodes, "connections": connections})
    assert r.status_code == 200, f"create template failed: {r.text}"
    return r.json()


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════

class TestHealth:
    """3.2 健康检查"""

    def test_health_ok(self):
        r = _get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "uptime" in data

    def test_index_returns_html(self):
        r = _get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


class TestFileUpload:
    """3.4 文件上传校验"""

    def test_upload_png(self):
        url = _upload_png()
        assert url.endswith(".png") or url.endswith(".jpg"), f"unexpected URL: {url}"
        assert "assets" in url, f"URL should contain assets: {url}"

    def test_upload_jpeg(self):
        r = _post("/api/assets/upload", files={"file": ("test.jpg", io.BytesIO(b"\xff\xd8\xff\xe0"), "image/jpeg")})
        assert r.status_code == 200, f"jpeg upload failed: {r.text}"

    def test_upload_reject_invalid_type(self):
        r = _post("/api/assets/upload", files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")})
        assert r.status_code == 400, f"expected 400, got {r.status_code}"

    def test_upload_reject_oversized(self):
        data = b"x" * (21 * 1024 * 1024)  # 21MB
        r = _post("/api/assets/upload", files={"file": ("big.png", io.BytesIO(data), "image/png")})
        assert r.status_code == 413, f"expected 413, got {r.status_code}"


class TestCanvasCRUD:
    """1.4 画布持久化 CRUD"""

    def test_save_and_list(self):
        r = _post("/api/canvas/save", json={
            "name": "E2E 测试画布",
            "nodes": [{"id": "n1", "type": "image_input", "x": 100, "y": 100, "data": {}}],
            "connections": [],
        })
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        canvas_id = data["id"]

        # 列表
        r2 = _get("/api/canvas/list")
        assert r2.status_code == 200
        canvases = r2.json()["canvases"]
        assert any(c["id"] == canvas_id for c in canvases)
        return canvas_id

    def test_load(self):
        canvas_id = self.test_save_and_list()
        r = _get(f"/api/canvas/{canvas_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["name"] == "E2E 测试画布"

    def test_load_404(self):
        r = _get("/api/canvas/nonexistent")
        assert r.status_code == 404

    def test_delete(self):
        canvas_id = self.test_save_and_list()
        r = _delete(f"/api/canvas/{canvas_id}")
        assert r.status_code == 200
        assert r.json()["deleted"] == canvas_id

        # 确认已删除
        r2 = _get(f"/api/canvas/{canvas_id}")
        assert r2.status_code == 404

    def test_delete_404(self):
        r = _delete("/api/canvas/nonexistent")
        assert r.status_code == 404


class TestCanvasRun:
    """画布执行（DAG 级联）"""

    def test_run_image_input_chain(self):
        """测试 image_input → gpt_image 链路（gpt-image-2 同步渠道）"""
        url = _upload_png()
        r = _post("/api/canvas/run", json={
            "nodes": [
                {"id": "img1", "type": "image_input", "x": 100, "y": 100, "data": {"image_url": url}},
                {"id": "gen1", "type": "gpt_image", "x": 400, "y": 100, "data": {"prompt": "a beautiful portrait", "model": "gpt-image-2", "resolution": "1024x1024", "aspect_ratio": "1:1"}},
            ],
            "connections": [{"id": "c1", "from": "img1", "to": "gen1"}],
        })
        assert r.status_code == 200, f"canvas run failed: {r.text}"
        data = r.json()
        canvas_id = data["canvas_id"]
        assert "node_statuses" in data

        # 轮询等待完成（最多等 300s，gpt-image-2 API 可能较慢）
        deadline = time.time() + 300
        gen_status = None
        while time.time() < deadline:
            r2 = _get(f"/api/canvas/{canvas_id}/nodes/gen1")
            assert r2.status_code == 200
            gen_status = r2.json()
            if gen_status["status"] in ("success", "failed", "blocked"):
                break
            time.sleep(3)
        assert gen_status["status"] == "success", f"gen1 status={gen_status.get('status')} error={gen_status.get('error')}"
        assert gen_status.get("image_url"), "gen1 should have image_url"

    def test_run_image_input_only(self):
        """测试纯 image_input 节点（无下游）"""
        url = _upload_png()
        r = _post("/api/canvas/run", json={
            "nodes": [
                {"id": "img1", "type": "image_input", "x": 100, "y": 100, "data": {"image_url": url}},
            ],
            "connections": [],
        })
        assert r.status_code == 200

    def test_node_status_404(self):
        r = _get("/api/canvas/nonexistent/nodes/n1")
        assert r.status_code == 404


class TestStreamerCRUD:
    """主播库 CRUD"""

    def test_create_and_list(self):
        st = _create_streamer("端到端测试主播")
        assert st["name"] == "端到端测试主播"
        assert st["id"].startswith("st_")

        r = _get("/api/streamers")
        assert r.status_code == 200
        streamers = r.json()["streamers"]
        assert any(s["id"] == st["id"] for s in streamers)
        return st

    def test_delete(self):
        st = self.test_create_and_list()
        r = _delete(f"/api/streamers/{st['id']}")
        assert r.status_code == 200
        # 确认已删除
        r2 = _get("/api/streamers")
        streamers = r2.json()["streamers"]
        assert not any(s["id"] == st["id"] for s in streamers)

    def test_delete_nonexistent(self):
        r = _delete("/api/streamers/st_nonexistent")
        # 非幂等删除不报错
        assert r.status_code == 200


class TestTemplateCRUD:
    """模板库 CRUD + 缩略图"""

    def test_create_and_list(self):
        tpl = _create_template("E2E 测试模板")
        assert tpl["name"] == "E2E 测试模板"
        assert tpl["id"].startswith("tpl_")

        r = _get("/api/templates")
        assert r.status_code == 200
        templates = r.json()["templates"]
        assert any(t["id"] == tpl["id"] for t in templates)
        return tpl

    def test_thumbnail_auto_generated(self):
        """1.3 模板缩略图自动生成"""
        # 创建带缩略图的模板
        tpl = _create_template("缩略图测试模板")
        r = _get("/api/templates")
        templates = r.json()["templates"]
        match = next((t for t in templates if t["id"] == tpl["id"]), None)
        assert match is not None
        assert match["thumbnail_url"] is not None, "thumbnail_url should be auto-generated from image_input"

    def test_get_detail(self):
        tpl = self.test_create_and_list()
        r = _get(f"/api/templates/{tpl['id']}")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data
        assert "connections" in data

    def test_get_404(self):
        r = _get("/api/templates/tpl_nonexistent")
        assert r.status_code == 404

    def test_delete(self):
        tpl = self.test_create_and_list()
        r = _delete(f"/api/templates/{tpl['id']}")
        assert r.status_code == 200
        r2 = _get(f"/api/templates/{tpl['id']}")
        assert r2.status_code == 404


class TestBatchOperations:
    """批量编排：run / list / adopt / retry / video"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """创建模板和主播供批量测试使用"""
        self.image_url = _upload_png()
        self.streamer = _create_streamer("批量测试主播", self.image_url)
        self.template = _create_template("批量测试模板", self.image_url)
        yield
        # 清理
        _delete(f"/api/streamers/{self.streamer['id']}")
        _delete(f"/api/templates/{self.template['id']}")

    def test_batch_run_and_list(self):
        """1.5 批量运行 + 列表"""
        r = _post("/api/batch/run", json={
            "template_id": self.template["id"],
            "streamer_ids": [self.streamer["id"]],
            "candidates_per_streamer": 1,
        })
        assert r.status_code == 200, f"batch run failed: {r.text}"
        batch_id = r.json()["batch_id"]
        assert batch_id.startswith("batch_")

        # 列表接口
        r2 = _get("/api/batch/list")
        assert r2.status_code == 200
        batches = r2.json()
        assert any(b["id"] == batch_id for b in batches)

        # 轮询等待完成（最多等 600s，gpt-image-2 API 可能较慢）
        deadline = time.time() + 600
        batch_status = None
        while time.time() < deadline:
            r3 = _get(f"/api/batch/{batch_id}")
            assert r3.status_code == 200, f"batch get failed: {r3.text}"
            batch_status = r3.json()
            if batch_status["status"] == "done":
                break
            time.sleep(3)
        assert batch_status["status"] == "done", f"batch not done: status={batch_status.get('status')} stats={batch_status.get('stats')}"

        # 检查 candidate 状态
        items = batch_status.get("items", [])
        assert len(items) > 0
        item = items[0]
        candidates = item.get("candidates", [])
        # 至少有一个成功或失败的候选
        assert len(candidates) > 0

        return batch_id, item, candidates

    def test_batch_adopt_and_retry(self):
        """4.2 候选采用 + 单项重试"""
        batch_id, item, candidates = self.test_batch_run_and_list()

        # 找到第一个成功的候选
        success_cand = next((c for c in candidates if c["status"] == "success"), None)
        if not success_cand:
            # 所有候选都失败了，尝试重试
            failed_cand = candidates[0]
            r = _post(f"/api/batch/{batch_id}/retry-candidate", json={
                "streamer_id": item["streamer_id"],
                "node_id": failed_cand["node_id"],
            })
            assert r.status_code == 200, f"retry failed: {r.text}"
            pytest.skip("所有候选失败，已触发重试")

        # 采用
        r = _post(f"/api/batch/{batch_id}/adopt", json={
            "streamer_id": item["streamer_id"],
            "node_id": success_cand["node_id"],
        })
        assert r.status_code == 200, f"adopt failed: {r.text}"

        # B2 修复后允许重复采用覆盖（前端已有确认弹窗），第二次应返回 200
        r2 = _post(f"/api/batch/{batch_id}/adopt", json={
            "streamer_id": item["streamer_id"],
            "node_id": success_cand["node_id"],
        })
        assert r2.status_code == 200, f"expected 200 for adopt overwrite (B2 fix), got {r2.status_code}"

    def test_batch_video(self):
        """1.1 视频生成参数可配置"""
        batch_id, item, candidates = self.test_batch_run_and_list()

        success_cand = next((c for c in candidates if c["status"] == "success"), None)
        if not success_cand:
            pytest.skip("无成功候选，跳过视频测试")

        # 先采用
        _post(f"/api/batch/{batch_id}/adopt", json={
            "streamer_id": item["streamer_id"],
            "node_id": success_cand["node_id"],
        })

        # 启动视频（自定义参数）
        r = _post(f"/api/batch/{batch_id}/video", json={
            "streamer_id": item["streamer_id"],
            "prompt": "camera slowly zooming in, cinematic lighting",
            "duration": "8",
            "aspect_ratio": "9:16",
        })
        assert r.status_code == 200, f"video start failed: {r.text}"
        data = r.json()
        # start_video 返回 batch item，含 phase2_canvas_id（与 phase1 候选画布区分）
        assert "phase2_canvas_id" in data

    def test_batch_404(self):
        r = _get("/api/batch/batch_nonexistent")
        assert r.status_code == 404

    def test_batch_list_empty(self):
        """列表接口在无数据时返回空数组"""
        r = _get("/api/batch/list")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestPhase1Compat:
    """Phase 1 兼容路由"""

    @pytest.mark.skip(reason="需对非 --reload 模式服务器运行；--reload 会清空内存中 TaskRegistry")
    def test_mock_run_and_poll(self):
        r = _post("/api/stages/mock/run", json={"workflow_id": "wf_test"})
        assert r.status_code == 200
        task_id = r.json()["task_id"]

        # 轮询
        deadline = time.time() + 30
        while time.time() < deadline:
            r2 = _get(f"/api/tasks/{task_id}")
            assert r2.status_code == 200
            if r2.json()["status"] in ("success", "failed"):
                break
            time.sleep(1)
        assert r2.json()["status"] == "success"

    def test_task_404(self):
        r = _get("/api/tasks/nonexistent")
        assert r.status_code == 404


class TestErrorHandling:
    """错误处理边界"""

    @pytest.mark.skip(reason="需对非 --reload 模式服务器运行；--reload 会清空内存中 TaskRegistry")
    def test_canvas_run_missing_input(self):
        """gpt_image 节点缺少输入图片应报错"""
        r = _post("/api/canvas/run", json={
            "nodes": [
                {"id": "gen1", "type": "gpt_image", "x": 100, "y": 100, "data": {"prompt": "test", "model": "gpt-image-2"}},
            ],
            "connections": [],
        })
        assert r.status_code == 200  # run 本身返回 200，但 gen1 会失败
        # 轮询确认失败
        canvas_id = r.json()["canvas_id"]
        deadline = time.time() + 30
        while time.time() < deadline:
            r2 = _get(f"/api/canvas/{canvas_id}/nodes/gen1")
            if r2.json()["status"] in ("success", "failed", "blocked"):
                break
            time.sleep(1)
        assert r2.json()["status"] == "failed"

    def test_batch_missing_template(self):
        r = _post("/api/batch/run", json={
            "template_id": "tpl_nonexistent",
            "streamer_ids": [],
            "candidates_per_streamer": 1,
        })
        assert r.status_code == 404

    def test_batch_missing_streamer(self):
        tpl = _create_template("404测试模板")
        r = _post("/api/batch/run", json={
            "template_id": tpl["id"],
            "streamer_ids": ["st_nonexistent"],
            "candidates_per_streamer": 1,
        })
        assert r.status_code == 404
        _delete(f"/api/templates/{tpl['id']}")


# ───────────────────────── 运行入口 ─────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])