"""存储抽象层。

LocalAdapter：本地磁盘 + FastAPI StaticFiles 对外提供 URL（MVP）。
后续可新增 NASAdapter / TOSAdapter，实现同一 StorageBackend 接口，业务层无感替换。
"""
import asyncio
import os
import uuid
from datetime import datetime
from typing import Protocol

import httpx


class StorageBackend(Protocol):
    async def save(self, data: bytes, ext: str) -> str:
        """保存数据，返回可访问 URL"""
        ...

    def url_to_path(self, url: str) -> str:
        """将 URL（如 /assets/2026/06/abc.png）转回本地文件路径。"""
        if url.startswith(self.base_url):
            rel = url[len(self.base_url):].lstrip("/")
            return os.path.join(self.root, rel.replace("/", os.sep))
        # 非 /assets 前缀的 URL 尝试直接作为路径返回
        return url

    async def download(self, url: str) -> bytes:
        """拉取远程 URL 内容本地化（用于 seedance 视频 24h 过期前下载保存）"""
        ...


class LocalAdapter:
    """本地磁盘存储，通过 /assets 静态挂载对外提供 URL"""

    def __init__(self, root: str = "assets", base_url: str = "/assets") -> None:
        self.root = root
        self.base_url = base_url

    async def save(self, data: bytes, ext: str) -> str:
        now = datetime.now()
        year = str(now.year)
        month = f"{now.month:02d}"
        filename = f"{uuid.uuid4().hex}.{ext.lstrip('.')}"
        abs_dir = os.path.join(self.root, year, month)
        file_path = os.path.join(abs_dir, filename)
        await asyncio.to_thread(self._write, abs_dir, file_path, data)
        # URL 始终用正斜杠，与平台无关
        return f"{self.base_url}/{year}/{month}/{filename}"

    async def download(self, url: str) -> bytes:
        # 本地资源（/assets/...）直接读盘，不走 HTTP
        if url.startswith(self.base_url):
            rel = url[len(self.base_url):].lstrip("/")
            local_path = os.path.join(self.root, rel.replace("/", os.sep))
            return await asyncio.to_thread(self._read, local_path)
        # 远程 URL（如 seedance 视频链接 24h 过期前下载）
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    @staticmethod
    def _read(local_path: str) -> bytes:
        with open(local_path, "rb") as f:
            return f.read()

    @staticmethod
    def _write(abs_dir: str, file_path: str, data: bytes) -> None:
        # 写盘前确保父目录存在（跨月/首次运行防 FileNotFoundError）
        os.makedirs(abs_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data)


# 模块级单例
storage = LocalAdapter()
