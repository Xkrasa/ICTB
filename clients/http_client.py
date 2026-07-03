"""全局共享 httpx AsyncClient。

所有对外 HTTP 请求（gpt-image-2 中转、RunningHub API、远程资产下载）复用
同一个 AsyncClient，避免每次请求新建/销毁 TCP 连接导致 TIME_WAIT 堆积
和端口耗尽。连接池按 host 自动池化，per-request timeout 覆盖构造默认值。

懒加载设计：非 FastAPI 入口（测试脚本直接 import orchestrator）也能用，
无需 lifespan 初始化；FastAPI 关闭时调 close_http_client() 优雅释放。
"""
import httpx

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """返回全局共享 AsyncClient（懒加载，关闭后自动重建）。"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=None,  # 默认无超时，由各调用方 per-request 传 timeout 覆盖
            limits=httpx.Limits(
                max_connections=30,
                max_keepalive_connections=15,
                keepalive_expiry=30.0,
            ),
        )
    return _client


async def close_http_client() -> None:
    """关闭全局 client（FastAPI lifespan shutdown 时调用）。"""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
