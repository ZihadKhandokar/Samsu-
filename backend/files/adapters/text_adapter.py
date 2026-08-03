from pathlib import Path
from typing import Any

from files.base_adapter import FileAdapter


class TextAdapter(FileAdapter):
    """UTF-8 source-code and text document adapter."""

    def __init__(self, max_bytes: int = 5 * 1024 * 1024):
        self.max_bytes = max_bytes

    def _encode(self, content: str) -> bytes:
        if not isinstance(content, str):
            raise TypeError("Text file content must be a string.")
        encoded = content.encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise ValueError("Text file exceeds the configured size limit.")
        return encoded

    def create(self, path: Path, payload: Any) -> dict[str, Any]:
        content = payload.get("content", "") if isinstance(payload, dict) else payload
        encoded = self._encode(content)
        path.write_bytes(encoded)
        return {"format": "text", "characters": len(content), "size": len(encoded)}

    def read(self, path: Path) -> dict[str, Any]:
        if path.stat().st_size > self.max_bytes:
            raise ValueError("Text file exceeds the configured read limit.")
        content = path.read_text(encoding="utf-8")
        return {
            "format": "text",
            "content": content,
            "characters": len(content),
            "lines": content.count("\n") + (1 if content else 0),
        }

    def edit(self, path: Path, operations: list[dict[str, Any]]) -> dict[str, Any]:
        content = path.read_text(encoding="utf-8")
        for operation in operations:
            name = operation.get("operation")
            if name == "replace":
                old = operation.get("old_text", "")
                new = operation.get("new_text", "")
                if not old:
                    raise ValueError("replace requires non-empty old_text.")
                count = content.count(old)
                if count != 1:
                    raise ValueError(
                        f"Expected old_text exactly once, found {count} occurrences."
                    )
                content = content.replace(old, new, 1)
            elif name == "append":
                addition = str(operation.get("content", ""))
                separator = "" if not content or content.endswith("\n") else "\n"
                content += separator + addition
            elif name == "prepend":
                addition = str(operation.get("content", ""))
                separator = "" if not addition or addition.endswith("\n") else "\n"
                content = addition + separator + content
            elif name == "replace_lines":
                start = int(operation["start_line"])
                end = int(operation["end_line"])
                if start < 1 or end < start:
                    raise ValueError("Invalid line range.")
                lines = content.splitlines(keepends=True)
                if end > len(lines):
                    raise ValueError("Line range exceeds file length.")
                replacement = str(operation.get("content", ""))
                if replacement and not replacement.endswith("\n"):
                    replacement += "\n"
                lines[start - 1 : end] = [replacement]
                content = "".join(lines)
            elif name == "overwrite":
                content = str(operation.get("content", ""))
            else:
                raise ValueError(f"Unsupported text operation: {name}")

        encoded = self._encode(content)
        path.write_bytes(encoded)
        return {"format": "text", "characters": len(content), "size": len(encoded)}

    def verify(self, path: Path) -> dict[str, Any]:
        result = super().verify(path)
        path.read_text(encoding="utf-8")
        result["encoding"] = "utf-8"
        return result
