"""任务注册表：SQLite 持久化 + 内存读缓存（WAL + threading.Lock）。"""
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger("orchestrator.registry")

RUNTIME_DIR = Path("runtime")
RUNTIME_TASKS_DIR = RUNTIME_DIR / "tasks"


def _task_key_to_filename(key: str) -> str:
    """将 registry key（含冒号）转为安全文件名。"""
    return key.replace(":", "__") + ".json"


class TaskRegistry:
    """任务注册表，SQLite 持久化 + 内存读缓存。

    - 内存字典作为读缓存，SQLite 作为持久存储（write-through）。
    - 启动时从 SQLite 恢复：运行中任务标记为 interrupted，
      避免进程重启后无后台协程接管的任务永久卡在 running。
    - 旧的 runtime/tasks/*.json 快照不再使用，启动时自动迁移。
    - 持久连接 + WAL 模式 + threading.Lock：消除高并发 database is locked。
    """

    # 终态：一旦进入这些状态，必须立即持久化
    _TERMINAL_STATES = {"success", "failed", "blocked", "interrupted"}

    def __init__(self, db_path: str = "runtime/tasks.db") -> None:
        self._tasks: dict = {}
        self._last_persisted_progress: dict[str, int] = {}
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        self._restore_from_db()
        self._migrate_json_snapshots()

    def _init_db(self) -> None:
        """初始化 SQLite 表结构 + WAL 模式。复用持久连接。"""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        # WAL：读写不互斥，消除 database is locked；NORMAL 同步级别兼顾安全与性能
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS task_records (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
            """)
            self._conn.commit()

    def _restore_from_db(self) -> None:
        """从 SQLite 恢复任务状态到内存缓存。"""
        with self._lock:
            rows = self._conn.execute("SELECT key, data FROM task_records").fetchall()
        for key, data_json in rows:
            try:
                rec = json.loads(data_json)
            except json.JSONDecodeError:
                continue
            self._tasks[key] = rec
            self._last_persisted_progress[key] = rec.get("progress", 0)

    def _migrate_json_snapshots(self) -> None:
        """一次性迁移旧的 runtime/tasks/*.json 快照到 SQLite，迁移后删除。"""
        if not RUNTIME_TASKS_DIR.exists():
            return
        json_files = list(RUNTIME_TASKS_DIR.glob("*.json"))
        if not json_files:
            return
        with self._lock:
            for f in json_files:
                try:
                    rec = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                key = f.stem.replace("__", ":")
                # 旧快照中运行中任务标记为 interrupted（兼容旧数据）
                if rec.get("status") in ("pending", "running"):
                    rec["status"] = "interrupted"
                    rec["error"] = "服务重启，任务已中断，请重试"
                self._conn.execute(
                    "INSERT OR REPLACE INTO task_records (key, data) VALUES (?, ?)",
                    (key, json.dumps(rec, ensure_ascii=False)),
                )
                self._tasks[key] = rec
                self._last_persisted_progress[key] = rec.get("progress", 0)
            self._conn.commit()
        # 迁移完成后删除旧快照文件
        for f in json_files:
            try:
                f.unlink()
            except OSError:
                pass
        logger.info("migrated %d JSON snapshots to SQLite", len(json_files))

    def _persist(self, key: str, rec: dict) -> None:
        """将单条记录写入 SQLite（write-through，复用持久连接）。"""
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO task_records (key, data) VALUES (?, ?)",
                    (key, json.dumps(rec, ensure_ascii=False)),
                )
                self._conn.commit()
            self._last_persisted_progress[key] = rec.get("progress", 0)
        except (sqlite3.Error, OSError) as e:
            # 持久化失败不影响内存逻辑，但记录日志便于排查
            logger.warning("persist failed for %s: %s", key, e)

    def _should_persist(self, key: str, rec: dict, fields: dict) -> bool:
        """判断是否需要写盘：终态必写，关键字段变更必写，进度每 10% 写一次。"""
        # 终态必写
        if rec.get("status") in self._TERMINAL_STATES:
            return True
        # status 变更必写
        if "status" in fields:
            return True
        # image_url / video_url / mask_url / error 变更必写
        if any(k in fields for k in ("image_url", "video_url", "mask_url", "error")):
            return True
        # 进度每 10% 写一次
        new_progress = rec.get("progress", 0)
        last = self._last_persisted_progress.get(key, 0)
        if new_progress // 10 != last // 10:
            return True
        return False

    # ───────────────────────── 持久化层（CRUD）─────────────────────────

    def get(self, task_id: str) -> dict | None:
        return self._tasks.get(task_id)

    def set(self, task_id: str, record: dict) -> None:
        self._tasks[task_id] = record
        self._persist(task_id, record)

    def update(self, task_id: str, **fields) -> dict | None:
        rec = self._tasks.get(task_id)
        if rec is None:
            return None
        rec.update(fields)
        rec["updated_at"] = time.time()
        if self._should_persist(task_id, rec, fields):
            self._persist(task_id, rec)
        return rec

    # ───────────────────────── 查询层（域查询，薄封装）─────────────────────────
    # 这两个方法遍历内存缓存做域特定查询。若未来存储换 NAS/TOS 或查询变复杂，
    # 可提取为独立 CanvasQuery 类（需 TaskStore 暴露 iter_all 接口）。

    def find_canvas_image_url(self, canvas_id: str, exclude_node_id: str) -> str | None:
        """在同一个 canvas 中查找可作为上游输入的 image_url。

        优先选 node_type == 'image_input' 且 status == 'success' 的节点，
        其次选任何 status == 'success' 且有 image_url 的节点。
        """
        prefix = f"{canvas_id}:"
        candidates = []
        for key, rec in self._tasks.items():
            if not key.startswith(prefix):
                continue
            nid = key[len(prefix):]
            if nid == exclude_node_id:
                continue
            if rec.get("status") != "success" or not rec.get("image_url"):
                continue
            candidates.append((rec.get("node_type", ""), rec["image_url"]))
        # 优先 image_input
        for ntype, url in candidates:
            if ntype == "image_input":
                return url
        # 其次任意成功节点
        if candidates:
            return candidates[0][1]
        return None

    def get_canvas_nodes(self, canvas_id: str) -> list[dict]:
        """批量返回某 canvas 下所有节点的实时状态（前端轮询聚合用）。

        遍历 registry 中 key 前缀为 "{canvas_id}:" 的记录，返回精简状态列表。
        替代前端 N 节点 N 次 GET 的逐节点轮询，降为 1 次 GET。
        """
        prefix = f"{canvas_id}:"
        result = []
        for key, rec in self._tasks.items():
            if not key.startswith(prefix):
                continue
            result.append({
                "node_id": rec.get("node_id"),
                "status": rec.get("status"),
                "progress": rec.get("progress", 0),
                "image_url": rec.get("image_url"),
                "video_url": rec.get("video_url"),
                "mask_url": rec.get("mask_url"),
                "error": rec.get("error"),
            })
        return result

    def close(self) -> None:
        """关闭持久连接（FastAPI lifespan 关闭时调用）。"""
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass


registry = TaskRegistry()
