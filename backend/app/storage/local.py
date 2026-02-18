import asyncio
import os
from pathlib import Path


class LocalStorage:
    def __init__(self, base_path: str):
        self._base = Path(base_path)
        self._base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        return self._base / key

    async def read_bytes(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"Storage key not found: {key}")
        return await asyncio.to_thread(path.read_bytes)

    async def write_bytes(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        await asyncio.to_thread(tmp_path.write_bytes, data)
        await asyncio.to_thread(os.rename, tmp_path, path)

    async def exists(self, key: str) -> bool:
        path = self._resolve(key)
        return await asyncio.to_thread(path.exists)

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if await asyncio.to_thread(path.exists):
            await asyncio.to_thread(path.unlink)

    async def list_keys(self, prefix: str) -> list[str]:
        base = self._resolve(prefix)
        if not await asyncio.to_thread(base.exists):
            return []

        def _walk() -> list[str]:
            keys = []
            for p in base.rglob("*"):
                if p.is_file():
                    keys.append(str(p.relative_to(self._base)))
            return sorted(keys)

        return await asyncio.to_thread(_walk)

    async def get_download_url(self, key: str, ttl_seconds: int = 3600) -> str:
        path = self._resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"Storage key not found: {key}")
        return str(path.resolve())
