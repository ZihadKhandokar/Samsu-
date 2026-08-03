import json
import re
from pathlib import Path
from typing import Any

import httpx

from files.adapter_registry import TEXT_EXTENSIONS


class FileGenerator:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: httpx.Timeout | None = None,
        max_tokens: int = 4096,
    ):
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.model = model
        self.timeout = timeout or httpx.Timeout(connect=30, read=None, write=60, pool=30)
        self.max_tokens = max_tokens

    def generate(
        self,
        request: str,
        project_root: str,
        file_spec: dict[str, Any],
        completed_files: list[str],
        existing: dict[str, Any] | None = None,
    ) -> Any:
        path = str(file_spec["path"])
        extension = Path(path).suffix.lower()
        structured = extension in {".docx", ".xlsx", ".xlsm", ".pptx", ".pdf"}
        system = self._structured_system(extension) if structured else self._text_system()
        existing_context = ""
        if existing:
            serialized = json.dumps(existing, ensure_ascii=False, default=str)
            existing_context = f"\nEXISTING FILE REPRESENTATION:\n{serialized[:7000]}\n"
        user = (
            f"PROJECT ROOT: {project_root}\n"
            f"TARGET FILE: {path}\n"
            f"PURPOSE: {file_spec.get('purpose', '')}\n"
            f"COMPLETED FILES: {', '.join(completed_files[-20:]) or 'none'}\n"
            f"PROJECT TASK:\n{request}\n"
            f"{existing_context}"
            "Produce the complete target file now."
        )
        content = self._complete(system, user)
        if structured:
            return self._parse_json(content)
        return self._strip_fence(content)

    @staticmethod
    def _text_system() -> str:
        return (
            "You generate one complete source-code or text file. Return only the raw "
            "file content: no Markdown fence, no filename heading, no explanation, "
            "no ellipsis, and no TODO placeholders. Keep imports and references "
            "consistent with the project task and completed files."
        )

    @staticmethod
    def _structured_system(extension: str) -> str:
        schemas = {
            ".docx": '{"title":"...","blocks":[{"type":"heading|paragraph|table|page_break","text":"...","level":1,"rows":[]}] }',
            ".xlsx": '{"sheets":[{"name":"Sheet1","rows":[["A","B"]],"header":true,"freeze_panes":"A2","column_widths":{"A":20}}]}',
            ".xlsm": '{"sheets":[{"name":"Sheet1","rows":[["A","B"]],"header":true}]}',
            ".pptx": '{"slides":[{"layout":0,"title":"...","body":["..."]}]}',
            ".pdf": '{"title":"...","page_size":"A4","blocks":[{"type":"heading|paragraph|page_break","text":"...","level":1}]}',
        }
        return (
            "You generate a complete structured-document specification. Return only "
            "strict JSON with no Markdown fence or explanation. Use this schema: "
            + schemas[extension]
        )

    def _complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.15,
            "max_tokens": self.max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.url, json=payload)
            response.raise_for_status()
            result = response.json()
        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError("llama.cpp returned no file content.")
        content = str((choices[0].get("message") or {}).get("content") or "")
        if not content.strip():
            raise RuntimeError("llama.cpp returned an empty file.")
        return content

    @staticmethod
    def _strip_fence(content: str) -> str:
        stripped = content.strip()
        match = re.fullmatch(r"```[^\n]*\n(.*)\n```", stripped, flags=re.S)
        return match.group(1) if match else content.strip("\n") + "\n"

    @classmethod
    def _parse_json(cls, content: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I | re.S)
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Structured file generator returned invalid JSON.")
            result = json.loads(cleaned[start : end + 1])
        if not isinstance(result, dict):
            raise ValueError("Structured file specification must be an object.")
        return result
