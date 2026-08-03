from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class FileAdapter(ABC):
    """Interface implemented by every workspace file format."""

    binary = False

    @abstractmethod
    def create(self, path: Path, payload: Any) -> dict[str, Any]:
        """Create a new file at *path* from a validated payload."""

    @abstractmethod
    def read(self, path: Path) -> dict[str, Any]:
        """Return a JSON-serializable representation for model context."""

    @abstractmethod
    def edit(self, path: Path, operations: list[dict[str, Any]]) -> dict[str, Any]:
        """Apply structured operations to an existing file."""

    def verify(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(f"File was not created: {path.name}")
        size = path.stat().st_size
        if size <= 0:
            raise ValueError(f"Created file is empty: {path.name}")
        return {"verified": True, "size": size}
