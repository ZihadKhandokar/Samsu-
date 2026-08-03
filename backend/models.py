from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(
        min_length=1
    )

    conversation_id: str = Field(
        min_length=1
    )

    message: str = Field(
        min_length=1
    )

    temperature: float | None = Field(
        default=None,
        ge=0,
        le=2,
    )

    max_tokens: int | None = Field(
        default=None,
        ge=1,
        le=8192,
    )

class ApprovalDecision(BaseModel):
    user_id: str = Field(
        min_length=1
    )

    conversation_id: str = Field(
        min_length=1
    )
    
class ChatResponse(BaseModel):
    conversation_id: str
    response: str


class ProfileUpdate(BaseModel):
    name: str | None = None
    preferred_language: str | None = None
    custom_instructions: str | None = None


class MemoryCreate(BaseModel):
    content: str = Field(
        min_length=1
    )

    importance: int = Field(
        default=5,
        ge=1,
        le=10,
    )


class MessageRecord(BaseModel):
    role: Literal[
        "user",
        "assistant",
        "system",
    ]

    content: str


class ToolRequest(BaseModel):
    operation: Literal[
        "list_directory",
        "read_file",
        "file_info",
        "search_files",
        "write_file",
        "edit_file",
        "rename_file",
        "delete_file",
    ]

    arguments: dict[str, Any] = Field(
        default_factory=dict
    )




    