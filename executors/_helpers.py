"""执行器共享辅助：RH 工作流进度回调工厂。"""
from typing import Callable


def make_rh_progress_cb(on_progress: Callable[[int], None],
                        queued_pct: int = 15) -> Callable[[str], None]:
    """构造 RH 工作流进度回调：QUEUED→queued_pct, RUNNING→渐进 +5（局部变量跟踪）。

    原 orchestrator._rh_progress_cb 读 registry 获取当前进度，深化后改为
    闭包局部变量，不碰 registry。
    """
    cur = [queued_pct]

    def cb(status: str) -> None:
        if status == "QUEUED":
            cur[0] = queued_pct
            on_progress(queued_pct)
        elif status == "RUNNING":
            cur[0] = min(cur[0] + 5, 80)
            on_progress(cur[0])

    return cb
