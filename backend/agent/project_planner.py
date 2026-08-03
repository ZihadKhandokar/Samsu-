import json
import re
from pathlib import PurePosixPath
from typing import Any

import httpx


class ProjectPlanner:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: httpx.Timeout | None = None,
        max_files: int = 100,
    ):
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.model = model
        self.timeout = timeout or httpx.Timeout(connect=30, read=None, write=60, pool=30)
        self.max_files = max_files

    def plan(
        self,
        request: str,
        project_root: str,
        phase_number: int = 1,
        phase_file_limit: int = 6,
        completed_files: list[str] | None = None,
    ) -> dict[str, Any]:
        phase_file_limit = min(max(int(phase_file_limit), 2), 10)
        completed_files = completed_files or []
        system = (
            "You are a software project planner. Return one strict JSON object and "
            "nothing else. Plan only ONE runnable phase as small, coherent files. Never "
            "include file content. Paths must be relative POSIX paths inside, but "
            "must not repeat, the given project root. Do not use '..' or absolute paths. Include config, "
            "source, tests, and README only when relevant. Prefer supported files: "
            "source/text, docx, xlsx, xlsm, pptx, or pdf. Split a large program "
            "into phases. Never repeat completed files unless they must be updated. "
            "Respect dependency order: configuration before libraries, libraries "
            "before entry points and tests, documentation last. Set has_more=true "
            "whenever any requested capability remains unimplemented, and describe "
            "the next bounded phase precisely in next_phase."
        )
        user = (
            f"PROJECT ROOT: {project_root}\n\n"
            f"CURRENT PHASE: {phase_number}\n"
            f"MAXIMUM FILES IN THIS PHASE: {phase_file_limit}\n"
            f"FILES COMPLETED BY EARLIER PHASES: "
            f"{', '.join(completed_files[-100:]) or 'none'}\n\n"
            f"USER TASK:\n{request}\n\n"
            "Return this schema:\n"
            '{"phase_title":"short title","has_more":true,'
            '"next_phase":"what the following phase should implement",'
            '"files":[{"path":"relative/path.ext","purpose":"why it exists",'
            '"operation":"create","dependencies":[]}]}'
        )
        content = self._complete(
            system,
            user,
            max_tokens=1600,
            response_schema=self._plan_schema(phase_file_limit),
        )
        data = self._parse_json_object(content)
        files = data.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("Planner returned no project files.")
        if len(files) > phase_file_limit:
            raise ValueError(f"Planner exceeded the {phase_file_limit}-file phase limit.")

        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in files:
            if not isinstance(raw, dict):
                raise ValueError("Every planned file must be an object.")
            path = str(raw.get("path", "")).replace("\\", "/").strip("/")
            path = self._remove_repeated_project_root(path, project_root)
            pure = PurePosixPath(path)
            if not path or pure.is_absolute() or ".." in pure.parts:
                raise ValueError(f"Unsafe planned path: {path!r}")
            key = path.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                {
                    "path": path,
                    "purpose": str(raw.get("purpose", "Project file")),
                    "operation": "update" if raw.get("operation") == "update" else "create",
                    "dependencies": [str(item) for item in raw.get("dependencies", [])],
                }
            )
        return {
            "phase_title": str(data.get("phase_title") or f"Phase {phase_number}"),
            "has_more": bool(data.get("has_more", False)),
            "next_phase": str(data.get("next_phase") or "").strip() or None,
            "files": normalized,
        }

    @staticmethod
    def _plan_schema(phase_file_limit: int) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["phase_title", "has_more", "next_phase", "files"],
            "properties": {
                "phase_title": {"type": "string"},
                "has_more": {"type": "boolean"},
                "next_phase": {"type": "string"},
                "files": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": phase_file_limit,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["path", "purpose", "operation", "dependencies"],
                        "properties": {
                            "path": {"type": "string"},
                            "purpose": {"type": "string"},
                            "operation": {"type": "string", "enum": ["create", "update"]},
                            "dependencies": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
        }

    @staticmethod
    def _remove_repeated_project_root(path: str, project_root: str) -> str:
        """Keep planned paths relative even when a small model repeats the root."""
        root = project_root.replace("\\", "/").strip("/")
        if not root:
            return path

        root_parts = PurePosixPath(root).parts
        path_parts = list(PurePosixPath(path).parts)
        root_key = tuple(part.casefold() for part in root_parts)

        # Remove the prefix repeatedly in case the model emitted it twice.
        while len(path_parts) >= len(root_parts):
            prefix = tuple(part.casefold() for part in path_parts[: len(root_parts)])
            if prefix != root_key:
                break
            path_parts = path_parts[len(root_parts) :]

        return PurePosixPath(*path_parts).as_posix() if path_parts else ""

    def _complete(
        self,
        system: str,
        user: str,
        max_tokens: int,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "schema": response_schema,
            }
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(self.url, json=payload)
            response.raise_for_status()
            result = response.json()
        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError("llama.cpp returned no planner response.")
        return str((choices[0].get("message") or {}).get("content") or "").strip()

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I | re.S)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Planner did not return valid JSON.")
            # Small local models occasionally emit literal newlines or tabs
            # inside JSON strings. strict=False accepts those control characters.
            value = json.loads(cleaned[start : end + 1], strict=False)
        if not isinstance(value, dict):
            raise ValueError("Planner response must be a JSON object.")
        return value
