"""FastAPI 入口：路由 + 长轮询 + 静态文件挂载 + 同源服务前端（免 CORS）。"""
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import orchestrator
from storage import storage

# StaticFiles 挂载要求目录已存在
os.makedirs("assets", exist_ok=True)

app = FastAPI(title="AI 团播资产画布 — Phase 0")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


# ---- Pydantic 入参/出参模型 ----
class MockRunRequest(BaseModel):
    workflow_id: str


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


# ---- 路由 ----
@app.get("/")
async def index():
    """同源服务前端单文件，免 CORS"""
    return FileResponse("index.html")


@app.post("/api/stages/mock/run")
async def mock_run(req: MockRunRequest):
    task_id = orchestrator.create_task(req.workflow_id, "mock", {})
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
