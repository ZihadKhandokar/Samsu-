import base64
import mimetypes
from pathlib import Path
from typing import Any

from files.base_adapter import FileAdapter


class BinaryAdapter(FileAdapter):
    """Fallback adapter: create/copy/inspect only, never semantic editing."""

    binary = True

    def create(self, path: Path, payload: Any) -> dict[str, Any]:
        if isinstance(payload, bytes):
            data = payload
        elif isinstance(payload, dict) and "base64" in payload:
            data = base64.b64decode(payload["base64"], validate=True)
        else:
            raise TypeError("Binary creation requires bytes or a base64 payload.")
        path.write_bytes(data)
        return {"format": "binary", "size": len(data)}

    def read(self, path: Path) -> dict[str, Any]:
        mime, _ = mimetypes.guess_type(path.name)
        return {
            "format": "binary",
            "name": path.name,
            "size": path.stat().st_size,
            "mime_type": mime or "application/octet-stream",
            "editable": False,
        }

    def edit(self, path: Path, operations: list[dict[str, Any]]) -> dict[str, Any]:
        raise ValueError("This binary format does not support semantic editing.")
