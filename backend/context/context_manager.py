import json
import re
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx

from config import settings
from context.chat_history import ChatHistory
from context.memory import MemoryStore
from context.prompt_builder import PromptBuilder
from context.user_profile import UserProfileStore
from tools.tool_definitions import FILE_TOOL_DEFINITIONS
from tools.tool_executor import ToolExecutor


class ContextManager:
    """Build model context and coordinate chat, streaming, and file tools."""

    MAX_TOOL_STEPS = 20
    MAX_TOOL_RESULT_CHARACTERS = 6000

    _AFFIRMATIVE_MESSAGES = {
        "yes",
        "yes do it",
        "yes, do it",
        "do it",
        "proceed",
        "go ahead",
        "confirm",
        "approved",
        "approve",
        "save it",
    }

    _FILE_TARGET_WORDS = (
        "file",
        "folder",
        "directory",
        "workspace",
        "imported document",
        "imported file",
        "the user imported these files",
    )

    _FILE_EXTENSION_PATTERN = re.compile(
        r"(?:^|[\s'\"`])[^\s'\"`]+\."
        r"(?:txt|md|json|yaml|yml|toml|ini|csv|xml|html|css|js|ts|jsx|tsx|"
        r"py|php|sql|dart|java|kt|kts|c|h|cpp|hpp|cs|go|rs|rb|sh|ps1|bat)\b",
        flags=re.IGNORECASE,
    )

    def __init__(self):
        self.chat_history = ChatHistory(settings.DATABASE_PATH)
        self.memory_store = MemoryStore(settings.DATABASE_PATH)
        self.user_profiles = UserProfileStore(settings.DATABASE_PATH)
        self.prompt_builder = PromptBuilder(
            system_prompt=settings.SYSTEM_PROMPT,
            max_context_tokens=settings.MAX_CONTEXT_TOKENS,
        )
        self.tool_executor = ToolExecutor()

    @staticmethod
    def _file_tool_instruction() -> dict[str, str]:
        return {
            "role": "system",
            "content": (
                "You have real file tools for the permitted workspace. All paths "
                "must be relative to that workspace. When the user explicitly asks "
                "to inspect a file, use a read-only tool. When the user explicitly "
                "asks to create, save, edit, rename, or delete a file, call the "
                "corresponding tool instead of describing a future action. Read an "
                "existing file before editing it. Never ask for approval in normal "
                "chat text: mutating tools create an approval request and the UI "
                "shows Approve and Reject buttons. Do not claim that a mutation "
                "succeeded until a tool result confirms it. Never access anything "
                "outside the permitted workspace."
            ),
        }

    def _prepare_messages(
        self,
        user_id: str,
        conversation_id: str,
        message: str,
        include_file_tools: bool = False,
    ) -> list[dict[str, Any]]:
        profile = self.user_profiles.get_profile(user_id)
        memories = self.memory_store.search_memories(
            user_id=user_id,
            query=message,
            limit=8,
        )
        history = self.chat_history.get_recent_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=40,
        )
        messages = self.prompt_builder.build_messages(
            current_message=message,
            profile=profile,
            memories=memories,
            history=history,
        )

        if include_file_tools:
            insert_at = 1 if messages else 0
            messages.insert(insert_at, self._file_tool_instruction())

        return messages

    @classmethod
    def _has_file_target(cls, message: str) -> bool:
        text = message.lower()
        return (
            any(word in text for word in cls._FILE_TARGET_WORDS)
            or bool(cls._FILE_EXTENSION_PATTERN.search(message))
        )

    @staticmethod
    def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in text for phrase in phrases)

    def _detect_requested_mutation(
        self,
        user_id: str,
        conversation_id: str,
        message: str,
    ) -> str | None:
        text = " ".join(message.strip().lower().split())

        delete_words = (
            "delete",
            "remove file",
            "remove the file",
            "erase file",
            "erase the file",
        )
        rename_words = (
            "rename",
            "move file",
            "move the file",
        )
        create_words = (
            "create file",
            "create a file",
            "create the file",
            "new file",
            "write a file",
            "generate a file",
            "save as",
            "save this as",
        )
        edit_words = (
            "edit",
            "fix",
            "correct",
            "update",
            "modify",
            "change",
            "rewrite",
            "append",
            "insert",
            "extend",
            "add line",
            "add lines",
            "add more lines",
            "save changes",
            "save the changes",
            "save the edit",
            "save the correction",
        )

        # Ordinary coding requests must not become real file mutations merely
        # because they contain words such as "add", "update", or "create".
        if self._has_file_target(message):
            if self._contains_any(text, delete_words):
                return "delete_file"
            if self._contains_any(text, rename_words):
                return "rename_file"
            if self._contains_any(text, create_words):
                return "write_file"
            if self._contains_any(text, edit_words):
                return "edit_file"

        if text not in self._AFFIRMATIVE_MESSAGES:
            return None

        # This is retained for compatibility with older chats. In the normal UI,
        # users should approve through the approval panel instead of typing "yes".
        recent_history = self.chat_history.get_recent_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=10,
        )
        recent_text = " ".join(
            str(item.get("content", "")).lower()
            for item in recent_history
        )

        if self._contains_any(recent_text, delete_words):
            return "delete_file"
        if self._contains_any(recent_text, rename_words):
            return "rename_file"
        if self._contains_any(recent_text, create_words):
            return "write_file"
        if self._contains_any(recent_text, edit_words):
            return "edit_file"
        return None

    def _should_use_file_tools(
        self,
        message: str,
        requested_mutation: str | None,
    ) -> bool:
        if requested_mutation is not None:
            return True

        text = " ".join(message.strip().lower().split())
        read_actions = (
            "read",
            "open",
            "inspect",
            "review",
            "show contents",
            "file info",
            "list files",
            "list directory",
            "search files",
            "search the workspace",
        )
        return self._has_file_target(message) and self._contains_any(
            text,
            read_actions,
        )

    async def chat(
        self,
        user_id: str,
        conversation_id: str,
        message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        messages = self._prepare_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
            include_file_tools=False,
        )
        result = await self._call_llama_cpp(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            use_tools=False,
        )
        content = str(result.get("content") or "").strip()
        if not content:
            raise RuntimeError("The model returned an empty response.")

        self.chat_history.add_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="user",
            content=message,
        )
        self.chat_history.add_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="assistant",
            content=content,
        )
        return content

    async def stream_chat(
        self,
        user_id: str,
        conversation_id: str,
        message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        requested_mutation = self._detect_requested_mutation(
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
        )
        use_file_tools = self._should_use_file_tools(
            message=message,
            requested_mutation=requested_mutation,
        )
        messages = self._prepare_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            message=message,
            include_file_tools=use_file_tools,
        )

        self.chat_history.add_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="user",
            content=message,
        )

        if not use_file_tools:
            response_parts: list[str] = []
            async for token in self._stream_llama_cpp_text(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                response_parts.append(token)
                yield {"type": "token", "token": token}

            response_text = "".join(response_parts).strip()
            if not response_text:
                raise RuntimeError("The model returned an empty response.")

            self.chat_history.add_message(
                user_id=user_id,
                conversation_id=conversation_id,
                role="assistant",
                content=response_text,
            )
            yield {
                "type": "done",
                "conversation_id": conversation_id,
            }
            return

        async for event in self._run_file_tool_loop(
            user_id=user_id,
            conversation_id=conversation_id,
            messages=messages,
            requested_mutation=requested_mutation,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield event

    async def _run_file_tool_loop(
        self,
        user_id: str,
        conversation_id: str,
        messages: list[dict[str, Any]],
        requested_mutation: str | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> AsyncIterator[dict[str, Any]]:
        edit_file_was_read = False
        seen_calls: set[str] = set()

        for _ in range(self.MAX_TOOL_STEPS):
            forced_tool: str | None = None
            if requested_mutation == "edit_file":
                forced_tool = "edit_file" if edit_file_was_read else "read_file"
            elif requested_mutation in {
                "write_file",
                "rename_file",
                "delete_file",
            }:
                forced_tool = requested_mutation

            assistant_message = await self._call_llama_cpp(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                use_tools=True,
                forced_tool=forced_tool,
            )
            tool_calls = assistant_message.get("tool_calls") or []
            legacy_call = assistant_message.get("function_call")
            if not tool_calls and legacy_call:
                tool_calls = [
                    {
                        "id": f"call_{uuid4().hex}",
                        "type": "function",
                        "function": legacy_call,
                    }
                ]

            if not tool_calls:
                content = str(assistant_message.get("content") or "").strip()
                if requested_mutation:
                    messages.append(
                        {"role": "assistant", "content": content or None}
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                f"Call the {forced_tool} tool now. Do not ask for "
                                "confirmation in chat; the UI handles approval."
                            ),
                        }
                    )
                    continue

                if not content:
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Respond with useful text or call the appropriate "
                                "file tool. Do not return an empty response."
                            ),
                        }
                    )
                    continue

                self.chat_history.add_message(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=content,
                )
                for chunk in self._text_chunks(content):
                    yield {"type": "token", "token": chunk}
                yield {
                    "type": "done",
                    "conversation_id": conversation_id,
                }
                return

            normalized_calls = [
                self._normalize_tool_call(raw_call)
                for raw_call in tool_calls
            ]
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.get("content"),
                    "tool_calls": [
                        item["message_call"] for item in normalized_calls
                    ],
                }
            )

            for item in normalized_calls:
                tool_name = item["name"]
                arguments = item["arguments"]
                tool_call_id = item["id"]
                signature = json.dumps(
                    {"name": tool_name, "arguments": arguments},
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )

                yield {
                    "type": "tool_status",
                    "message": f"Using {tool_name}...",
                }

                if signature in seen_calls:
                    duplicate_result = {
                        "status": "error",
                        "error": (
                            "This identical tool call was already attempted. Use "
                            "the previous result or choose a different operation."
                        ),
                    }
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": self._serialize_tool_result(
                                duplicate_result
                            ),
                        }
                    )
                    continue

                seen_calls.add(signature)
                try:
                    result = self.tool_executor.request(
                        operation=tool_name,
                        arguments=arguments,
                    )
                except Exception as error:
                    result = {
                        "status": "error",
                        "error": f"{type(error).__name__}: {error}",
                    }

                if tool_name == "read_file" and result.get("status") == "completed":
                    edit_file_was_read = True

                if result.get("status") == "approval_required":
                    approval = result["approval"]
                    public_approval = {
                        "id": approval["id"],
                        "action": approval["action"],
                        "preview": approval["preview"],
                        "status": approval["status"],
                        "expires_at": approval["expires_at"],
                    }
                    approval_message = (
                        f"I prepared a file operation ({approval['action']}). "
                        "Review the proposed change and use the approval panel."
                    )
                    self.chat_history.add_message(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        role="assistant",
                        content=approval_message,
                    )
                    yield {
                        "type": "approval",
                        "message": approval_message,
                        "approval": public_approval,
                    }
                    return

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": self._serialize_tool_result(result),
                    }
                )

        # Preserve a useful response instead of ending with an abrupt tool-limit
        # message. Tools are disabled for this final recovery response.
        messages.append(
            {
                "role": "system",
                "content": (
                    "Stop calling tools. Explain briefly what remains unfinished "
                    "and give the most useful next action. Do not claim that an "
                    "unconfirmed file operation succeeded."
                ),
            }
        )
        response_parts: list[str] = []
        async for token in self._stream_llama_cpp_text(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            response_parts.append(token)
            yield {"type": "token", "token": token}

        response_text = "".join(response_parts).strip()
        if not response_text:
            response_text = (
                "I could not complete the remaining file-tool steps. Please "
                "retry the specific file operation."
            )
            yield {"type": "token", "token": response_text}

        self.chat_history.add_message(
            user_id=user_id,
            conversation_id=conversation_id,
            role="assistant",
            content=response_text,
        )
        yield {"type": "done", "conversation_id": conversation_id}

    async def _stream_llama_cpp_text(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int | None,
    ) -> AsyncIterator[str]:
        url = settings.LLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": settings.LLAMA_MODEL,
            "messages": messages,
            "temperature": (
                temperature if temperature is not None else settings.TEMPERATURE
            ),
            "max_tokens": (
                max_tokens
                if max_tokens is not None
                else settings.MAX_RESPONSE_TOKENS
            ),
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        timeout = self._http_timeout()

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw_data = line[5:].strip()
                    if not raw_data:
                        continue
                    if raw_data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    token = delta.get("content")
                    if isinstance(token, str) and token:
                        yield token

    async def _call_llama_cpp(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int | None,
        use_tools: bool,
        forced_tool: str | None = None,
    ) -> dict[str, Any]:
        url = settings.LLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
        payload: dict[str, Any] = {
            "model": settings.LLAMA_MODEL,
            "messages": messages,
            "temperature": (
                temperature if temperature is not None else settings.TEMPERATURE
            ),
            "max_tokens": (
                max_tokens
                if max_tokens is not None
                else settings.MAX_RESPONSE_TOKENS
            ),
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "parallel_tool_calls": False,
        }
        if use_tools:
            payload["tools"] = FILE_TOOL_DEFINITIONS
            payload["parse_tool_calls"] = True
            payload["tool_choice"] = (
                {
                    "type": "function",
                    "function": {"name": forced_tool},
                }
                if forced_tool
                else "auto"
            )

        async with httpx.AsyncClient(timeout=self._http_timeout()) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

        choices = result.get("choices") or []
        if not choices:
            raise RuntimeError("llama.cpp returned no choices.")
        return choices[0].get("message") or {}

    @staticmethod
    def _http_timeout() -> httpx.Timeout:
        return httpx.Timeout(
            connect=10.0,
            read=900.0,
            write=30.0,
            pool=10.0,
        )

    def _normalize_tool_call(
        self,
        raw_call: dict[str, Any],
    ) -> dict[str, Any]:
        function = raw_call.get("function") or {}
        name = function.get("name")
        if not name:
            raise ValueError("Tool call has no function name.")

        raw_arguments = function.get("arguments") or {}
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments or "{}")
            except json.JSONDecodeError as error:
                raise ValueError(
                    "Tool arguments contained invalid JSON."
                ) from error
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            raise ValueError("Tool arguments must be a JSON object.")

        tool_call_id = raw_call.get("id") or f"call_{uuid4().hex}"
        return {
            "id": tool_call_id,
            "name": name,
            "arguments": arguments,
            "message_call": {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            },
        }

    def _serialize_tool_result(self, result: Any) -> str:
        serialized = json.dumps(
            result,
            ensure_ascii=False,
            default=str,
        )
        if len(serialized) > self.MAX_TOOL_RESULT_CHARACTERS:
            serialized = (
                serialized[: self.MAX_TOOL_RESULT_CHARACTERS]
                + "\n[Tool result truncated]"
            )
        return serialized

    @staticmethod
    def _text_chunks(text: str) -> list[str]:
        return re.findall(
            r".{1,24}(?:\s+|$)|.{1,24}",
            text,
            flags=re.DOTALL,
        )
