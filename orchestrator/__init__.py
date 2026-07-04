"""orchestrator 包：聚合 registry / phase1 / engine / batch 公共接口。

main.py 通过 orchestrator.xxx 访问，拆包后接口不变。
"""
from .registry import registry, TaskRegistry
from ._shared import classify_error, _record_image_size, SEM, _background_tasks
from .phase1 import create_task
from .engine import execute_canvas, approve_node, reject_node
from .batch import (
    execute_batch, aggregate_batch, list_batches,
    adopt_batch, retry_candidate, start_video,
)

__all__ = [
    "registry", "TaskRegistry", "classify_error",
    "create_task", "execute_canvas", "approve_node", "reject_node",
    "execute_batch", "aggregate_batch", "list_batches",
    "adopt_batch", "retry_candidate", "start_video",
]
