"""FastAPI 入口：路由 + 长轮询 + 静态文件挂载 + 同源服务前端（免 CORS）。"""
import json
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("main")

_start_time = time.time()

os.makedirs("assets", exist_ok=True)
os.makedirs("static", exist_ok=True)
CANVAS_DIR = Path("canvases")
CANVAS_DIR.mkdir(exist_ok=True)
STREAMER_DIR = Path("streamers")
STREAMER_DIR.mkdir(exist_ok=True)
TEMPLATE_DIR = Path("templates")
TEMPLATE_DIR.mkdir(exist_ok=True)
from storage import storage

app = FastAPI(title="AI 团播资产画布 — Phase 3")


# ───────────────────────── API Key 访问控制 ─────────────────────────

@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    """非空 API_KEY 时，所有 /api/* 路由需携带 X-API-Key Header 或 api_key Query。"""
    if config.API_KEY and request.url.path.startswith("/api/"):
        key = request.headers.get("X-API-Key") or request.query_params.get("api_key", "")
        if key != config.API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


# ───────────────────────── Pydantic 模型 ─────────────────────────

class MockRunRequest(BaseModel):
    workflow_id: str


class CharacterRunRequest(BaseModel):
    workflow_id: str
    reference_image_url: str
    hair: str
    makeup: str
    clothing: str


class AssetUploadResponse(BaseModel):
    url: str


class TaskAssets(BaseModel):
    character_png: str | None = None
    poster_png: str | None = None
    video_mp4: str | None = None


class TaskStatusResponse(BaseModel):
    status: str
    stage: str
    progress: int
    assets: TaskAssets
    error: str | None = None


# Phase 2 画布模型
class NodeData(BaseModel):
    id: str
    type: str
    x: float = 0
    y: float = 0
    data: dict = {}


class ConnectionData(BaseModel):
    id: str
    from_node: str
    to: str

    model_config = {"populate_by_name": True}

    def __init__(self, **data):
        if "from" in data:
            data["from_node"] = data.pop("from")
        super().__init__(**data)


class CanvasRunRequest(BaseModel):
    nodes: list[NodeData]
    connections: list[ConnectionData]


# ───────────────────────── 路由 ─────────────────────────

@app.get("/")
async def index():
    """同源服务前端单文件，免 CORS"""
    return FileResponse("index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "uptime": time.time() - _start_time}


# ---- Phase 1 兼容路由 ----

@app.post("/api/stages/mock/run")
async def mock_run(req: MockRunRequest):
    task_id = orchestrator.create_task(req.workflow_id, "mock", {})
    return {"task_id": task_id}


@app.post("/api/stages/character/run")
async def character_run(req: CharacterRunRequest):
    task_id = orchestrator.create_task(
        req.workflow_id,
        "character",
        {
            "reference_image_url": req.reference_image_url,
            "hair": req.hair,
            "makeup": req.makeup,
            "clothing": req.clothing,
        },
    )
    return {"task_id": task_id}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    rec = orchestrator.registry.get(task_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskStatusResponse(
        status=rec["status"],
        stage=rec["stage"],
        progress=rec["progress"],
        assets=TaskAssets(**rec["assets"]),
        error=rec["error"],
    )


@app.post("/api/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 20MB 限制")
    allowed_types = {"image/png", "image/jpeg", "image/webp", "image/gif", "video/mp4"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    ext = (file.filename or "bin").rsplit(".", 1)[-1].lower() or "bin"
    url = await storage.save(data, ext)
    return AssetUploadResponse(url=url)


# ---- Phase 2 画布路由 ----

@app.post("/api/canvas/run")
async def canvas_run(req: CanvasRunRequest):
    """执行画布：接收节点和连线，启动 DAG 级联执行"""
    canvas_id = uuid.uuid4().hex
    nodes = [n.model_dump() for n in req.nodes]
    conns = [{"id": c.id, "from": c.from_node, "to": c.to} for c in req.connections]
    node_statuses = orchestrator.execute_canvas(canvas_id, nodes, conns)
    return {"canvas_id": canvas_id, "node_statuses": node_statuses}


@app.get("/api/canvas/{canvas_id}/nodes/{node_id}")
async def get_node_status(canvas_id: str, node_id: str):
    """查询单个节点的实时状态（前端轮询用）"""
    rec = orchestrator.registry.get(f"{canvas_id}:{node_id}")
    if rec is None:
        raise HTTPException(status_code=404, detail="node not found")
    return {
        "status": rec["status"],
        "progress": rec["progress"],
        "image_url": rec.get("image_url"),
        "video_url": rec.get("video_url"),
        "error": rec.get("error"),
    }


# ---- Phase 3 画布持久化 ----

class CanvasSaveRequest(BaseModel):
    name: str = ""
    nodes: list
    connections: list


@app.post("/api/canvas/save")
async def canvas_save(req: CanvasSaveRequest):
    """保存画布 JSON 到 canvases/ 目录"""
    canvas_id = uuid.uuid4().hex[:8]
    name = req.name or f"画布_{canvas_id}"
    data = {
        "id": canvas_id,
        "name": name,
        "nodes": req.nodes,
        "connections": req.connections,
        "saved_at": time.time(),
    }
    (CANVAS_DIR / f"{canvas_id}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"id": canvas_id, "name": name}


@app.get("/api/canvas/list")
async def canvas_list():
    """列出所有已保存的画布"""
    result = []
    for f in sorted(CANVAS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({
                "id": data["id"],
                "name": data["name"],
                "saved_at": data["saved_at"],
                "node_count": len(data.get("nodes", [])),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return {"canvases": result}


@app.get("/api/canvas/{canvas_id}")
async def canvas_load(canvas_id: str):
    """加载画布 JSON"""
    f = CANVAS_DIR / f"{canvas_id}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="canvas not found")
    return json.loads(f.read_text(encoding="utf-8"))


@app.delete("/api/canvas/{canvas_id}")
async def canvas_delete(canvas_id: str):
    """删除已保存的画布"""
    f = CANVAS_DIR / f"{canvas_id}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="canvas not found")
    f.unlink()
    return {"deleted": canvas_id}


# ───────────────────────── 主播库 ─────────────────────────

class StreamerRequest(BaseModel):
    name: str
    source_image_url: str
    tag: str = ""


@app.get("/api/streamers")
async def streamer_list():
    """列出所有主播（按创建时间倒序）"""
    items = []
    for f in sorted(STREAMER_DIR.glob("st_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError):
            continue
    return {"streamers": items}


@app.post("/api/streamers")
async def streamer_create(req: StreamerRequest):
    """新建主播：name + 原图 URL（avatar 复用原图）"""
    sid = "st_" + uuid.uuid4().hex[:10]
    data = {
        "id": sid,
        "name": req.name,
        "avatar_url": req.source_image_url,
        "source_image_url": req.source_image_url,
        "tag": req.tag,
        "created_at": time.time(),
    }
    (STREAMER_DIR / f"{sid}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


@app.delete("/api/streamers/{sid}")
async def streamer_delete(sid: str):
    f = STREAMER_DIR / f"{sid}.json"
    if f.exists():
        f.unlink()
    return {"ok": True}


# ───────────────────────── 模板库 ─────────────────────────

class TemplateRequest(BaseModel):
    name: str = ""
    category: str = ""
    nodes: list
    connections: list


@app.get("/api/templates")
async def template_list():
    """列出所有模板（列表项不含 nodes 明细，按时间倒序）"""
    items = []
    for f in sorted(TEMPLATE_DIR.glob("tpl_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            items.append({
                "id": d["id"],
                "name": d["name"],
                "category": d.get("category", ""),
                "thumbnail_url": d.get("thumbnail_url"),
                "node_count": len(d.get("nodes", [])),
                "saved_at": d.get("saved_at"),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return {"templates": items}


@app.post("/api/templates")
async def template_create(req: TemplateRequest):
    """从画布存为模板（nodes/connections 即画布结构）"""
    tid = "tpl_" + uuid.uuid4().hex[:10]
    name = req.name or f"模板_{tid}"
    # 自动提取缩略图：取第一个 image_input 节点的 image_url
    thumbnail_url = None
    for n in req.nodes:
        if n.get("type") == "image_input" and n.get("data", {}).get("image_url"):
            thumbnail_url = n["data"]["image_url"]
            break
    data = {
        "id": tid,
        "name": name,
        "category": req.category,
        "thumbnail_url": thumbnail_url,
        "nodes": req.nodes,
        "connections": req.connections,
        "saved_at": time.time(),
    }
    (TEMPLATE_DIR / f"{tid}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"id": tid, "name": name, "thumbnail_url": thumbnail_url}


@app.get("/api/templates/{tid}")
async def template_get(tid: str):
    """加载模板详情（含 nodes/connections，供批量克隆用）"""
    f = TEMPLATE_DIR / f"{tid}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="template not found")
    return json.loads(f.read_text(encoding="utf-8"))


@app.delete("/api/templates/{tid}")
async def template_delete(tid: str):
    f = TEMPLATE_DIR / f"{tid}.json"
    if f.exists():
        f.unlink()
    return {"ok": True}


# ───────────────────────── 批量生产 ─────────────────────────

class BatchRunRequest(BaseModel):
    template_id: str
    streamer_ids: list
    candidates_per_streamer: int = 3


@app.post("/api/batch/run")
async def batch_run(req: BatchRunRequest):
    """启动批量生产：加载模板 + 主播，为每个主播克隆链路并启动 canvas run"""
    tpl_path = TEMPLATE_DIR / f"{req.template_id}.json"
    if not tpl_path.exists():
        raise HTTPException(status_code=404, detail="template not found")
    template = json.loads(tpl_path.read_text(encoding="utf-8"))

    streamers = []
    for sid in req.streamer_ids:
        sp = STREAMER_DIR / f"{sid}.json"
        if not sp.exists():
            raise HTTPException(status_code=404, detail=f"streamer {sid} not found")
        streamers.append(json.loads(sp.read_text(encoding="utf-8")))

    batch = await orchestrator.execute_batch(
        template, streamers, req.candidates_per_streamer
    )
    return {"batch_id": batch["id"]}


@app.get("/api/batch/list")
async def batch_list():
    """列出所有历史批次（摘要：id / 模板名 / 状态 / 创建时间 / 主播数）"""
    return orchestrator.list_batches()


@app.get("/api/batch/{batch_id}")
async def batch_get(batch_id: str):
    """聚合查询批量任务状态（前端 2s 轮询单接口）"""
    try:
        return orchestrator.aggregate_batch(batch_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="batch not found")


class AdoptRequest(BaseModel):
    streamer_id: str
    node_id: str


class VideoRequest(BaseModel):
    streamer_id: str
    prompt: str
    duration: str = "8"
    aspect_ratio: str = "9:16"


@app.post("/api/batch/{batch_id}/adopt")
async def batch_adopt(batch_id: str, req: AdoptRequest):
    """候选采用：记录 adopted_node_id/adopted_image_url，作为人工断点"""
    try:
        return orchestrator.adopt_batch(batch_id, req.streamer_id, req.node_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="batch not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class RetryCandidateRequest(BaseModel):
    streamer_id: str
    node_id: str


@app.post("/api/batch/{batch_id}/retry-candidate")
async def batch_retry_candidate(batch_id: str, req: RetryCandidateRequest):
    """重试单个失败/中断候选"""
    try:
        return await orchestrator.retry_candidate(batch_id, req.streamer_id, req.node_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="batch not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/batch/{batch_id}/video")
async def batch_video(batch_id: str, req: VideoRequest):
    """基于采用图启动视频生成：构造 image_input→seedance_video 单链路 canvas run"""
    try:
        return await orchestrator.start_video(
            batch_id, req.streamer_id, req.prompt,
            duration=req.duration, aspect_ratio=req.aspect_ratio,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="batch not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
