"""FastAPI 入口：路由 + 长轮询 + 静态文件挂载 + 同源服务前端（免 CORS）。"""
import json
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import orchestrator

os.makedirs("assets", exist_ok=True)
CANVAS_DIR = Path("canvases")
CANVAS_DIR.mkdir(exist_ok=True)
from storage import storage

app = FastAPI(title="AI 团播资产画布 — Phase 3")
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
