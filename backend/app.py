import json
import logging
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import (
    FileResponse,
    StreamingResponse,
)

from agent.file_generator import FileGenerator
from agent.graph import WorkspaceAgentRuntime
from agent.project_planner import ProjectPlanner
from agent.routes import (
    WorkspaceAgentService,
    create_agent_router,
)
from config import settings
from context.context_manager import ContextManager
from files.workspace_manager import WorkspaceManager
from models import (
    ApprovalDecision,
    ChatRequest,
    ChatResponse,
    MemoryCreate,
    ProfileUpdate,
    ToolRequest,
)


logger = logging.getLogger(__name__)


app = FastAPI(
    title="Samsu++ Context API",
    version="2.0.0",
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


# -------------------------------------------------
# Existing chat context manager
# -------------------------------------------------

context_manager = ContextManager()

tool_executor = context_manager.tool_executor


# -------------------------------------------------
# New secure workspace manager
# -------------------------------------------------

workspace_manager = WorkspaceManager(
    workspace_root=settings.WORKSPACE_ROOT,
    database_path=settings.DATABASE_PATH,
    max_file_bytes=(
        settings.MAX_FILE_SIZE_BYTES
    ),
)


# -------------------------------------------------
# New persistent project-building agent
# -------------------------------------------------

workspace_agent = WorkspaceAgentRuntime(
    workspace=workspace_manager,
    planner=ProjectPlanner(
        base_url=settings.LLAMA_BASE_URL,
        model=settings.LLAMA_MODEL,
    ),
    generator=FileGenerator(
        base_url=settings.LLAMA_BASE_URL,
        model=settings.LLAMA_MODEL,
        max_tokens=(
            settings.MAX_RESPONSE_TOKENS
        ),
    ),
    checkpoint_path=(
        settings.AGENT_CHECKPOINT_PATH
    ),
)

agent_service = WorkspaceAgentService(
    workspace_agent
)

app.include_router(
    create_agent_router(agent_service)
)


# -------------------------------------------------
# Application lifecycle
# -------------------------------------------------

@app.on_event("shutdown")
def shutdown_services():
    agent_service.close()
    workspace_agent.close()


# -------------------------------------------------
# Web interface
# -------------------------------------------------

@app.get(
    "/",
    include_in_schema=False,
)
async def chat_interface():
    index_file = STATIC_DIR / "index.html"

    if not index_file.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                "static/index.html was not found."
            ),
        )

    return FileResponse(index_file)


# -------------------------------------------------
# Health
# -------------------------------------------------

@app.get("/health")
async def health():
    llama_status = "unavailable"

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0)
        ) as client:
            response = await client.get(
                (
                    settings.LLAMA_BASE_URL.rstrip("/")
                    + "/v1/models"
                )
            )

            if response.is_success:
                llama_status = "available"

    except httpx.HTTPError:
        llama_status = "unavailable"

    return {
        "status": "ok",
        "llama_cpp": llama_status,
        "model": settings.LLAMA_MODEL,
        "workspace": str(
            workspace_manager.root
        ),
    }


# -------------------------------------------------
# Non-streaming chat
# -------------------------------------------------

@app.post(
    "/chat",
    response_model=ChatResponse,
)
async def chat(
    request: ChatRequest,
):
    try:
        response_text = (
            await context_manager.chat(
                user_id=request.user_id,
                conversation_id=(
                    request.conversation_id
                ),
                message=request.message,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )
        )

        return ChatResponse(
            conversation_id=(
                request.conversation_id
            ),
            response=response_text,
        )

    except httpx.ConnectError as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "Could not connect to llama.cpp."
            ),
        ) from error

    except httpx.TimeoutException as error:
        raise HTTPException(
            status_code=504,
            detail=(
                "llama.cpp timed out: "
                f"{error!r}"
            ),
        ) from error

    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "llama.cpp returned "
                f"{error.response.status_code}: "
                f"{error.response.text}"
            ),
        ) from error

    except Exception as error:
        logger.exception(
            "Unexpected chat error"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(error).__name__}: "
                f"{error!r}"
            ),
        ) from error


# -------------------------------------------------
# Streaming chat
# -------------------------------------------------

@app.post("/chat/stream")
async def stream_chat(
    request: ChatRequest,
):
    async def generate():
        try:
            async for event in (
                context_manager.stream_chat(
                    user_id=request.user_id,
                    conversation_id=(
                        request.conversation_id
                    ),
                    message=request.message,
                    temperature=(
                        request.temperature
                    ),
                    max_tokens=(
                        request.max_tokens
                    ),
                )
            ):
                event_type = event.get(
                    "type",
                    "token",
                )

                if event_type == "token":
                    payload = {
                        "token": event.get(
                            "token",
                            "",
                        ),
                    }

                    yield (
                        "data: "
                        + json.dumps(
                            payload,
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )

                elif event_type == "tool_status":
                    payload = {
                        "message": event.get(
                            "message",
                            "",
                        ),
                    }

                    yield (
                        "event: tool_status\n"
                        "data: "
                        + json.dumps(
                            payload,
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )

                elif event_type == "approval":
                    payload = {
                        "message": event.get(
                            "message",
                            "",
                        ),
                        "approval": event.get(
                            "approval",
                            {},
                        ),
                    }

                    yield (
                        "event: approval\n"
                        "data: "
                        + json.dumps(
                            payload,
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )

                elif event_type == "error":
                    payload = {
                        "error": event.get(
                            "error",
                            "Unknown streaming error.",
                        ),
                    }

                    yield (
                        "event: error\n"
                        "data: "
                        + json.dumps(
                            payload,
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )

            yield (
                "event: done\n"
                "data: {}\n\n"
            )

        except httpx.ConnectError:
            payload = {
                "error": (
                    "Could not connect to llama.cpp."
                ),
            }

            yield (
                "event: error\n"
                "data: "
                + json.dumps(payload)
                + "\n\n"
            )

        except httpx.TimeoutException as error:
            payload = {
                "error": (
                    "llama.cpp timed out: "
                    f"{error!r}"
                ),
            }

            yield (
                "event: error\n"
                "data: "
                + json.dumps(payload)
                + "\n\n"
            )

        except Exception as error:
            logger.exception(
                "Streaming chat failed"
            )

            payload = {
                "error": (
                    f"{type(error).__name__}: "
                    f"{error!r}"
                ),
            }

            yield (
                "event: error\n"
                "data: "
                + json.dumps(
                    payload,
                    ensure_ascii=False,
                )
                + "\n\n"
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": (
                "no-cache, no-transform"
            ),
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# -------------------------------------------------
# Conversation history
# -------------------------------------------------

@app.get(
    "/users/{user_id}/conversations"
)
async def list_conversations(
    user_id: str,
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
):
    return (
        context_manager
        .chat_history
        .list_conversations(
            user_id,
            limit,
        )
    )


@app.get(
    "/users/{user_id}/conversations/"
    "{conversation_id}/messages"
)
async def get_conversation_messages(
    user_id: str,
    conversation_id: str,
):
    return (
        context_manager
        .chat_history
        .get_conversation_messages(
            user_id=user_id,
            conversation_id=(
                conversation_id
            ),
        )
    )


@app.delete(
    "/users/{user_id}/conversations/"
    "{conversation_id}"
)
async def clear_conversation(
    user_id: str,
    conversation_id: str,
):
    deleted = (
        context_manager
        .chat_history
        .clear_conversation(
            user_id=user_id,
            conversation_id=(
                conversation_id
            ),
        )
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found.",
        )

    return {
        "message": (
            "Conversation deleted successfully."
        ),
    }


# -------------------------------------------------
# User profile
# -------------------------------------------------

@app.put(
    "/users/{user_id}/profile"
)
async def update_profile(
    user_id: str,
    profile: ProfileUpdate,
):
    context_manager.user_profiles.update_profile(
        user_id=user_id,
        name=profile.name,
        preferred_language=(
            profile.preferred_language
        ),
        custom_instructions=(
            profile.custom_instructions
        ),
    )

    return {
        "message": (
            "Profile updated successfully."
        ),
    }


@app.get(
    "/users/{user_id}/profile"
)
async def get_profile(
    user_id: str,
):
    return (
        context_manager
        .user_profiles
        .get_profile(user_id)
    )


# -------------------------------------------------
# Long-term memory
# -------------------------------------------------

@app.post(
    "/users/{user_id}/memories"
)
async def create_memory(
    user_id: str,
    memory: MemoryCreate,
):
    memory_id = (
        context_manager
        .memory_store
        .add_memory(
            user_id=user_id,
            content=memory.content,
            importance=memory.importance,
        )
    )

    return {
        "id": memory_id,
        "message": (
            "Memory saved successfully."
        ),
    }


@app.get(
    "/users/{user_id}/memories"
)
async def list_memories(
    user_id: str,
):
    return (
        context_manager
        .memory_store
        .list_memories(user_id)
    )


@app.delete(
    "/users/{user_id}/memories/"
    "{memory_id}"
)
async def delete_memory(
    user_id: str,
    memory_id: int,
):
    deleted = (
        context_manager
        .memory_store
        .delete_memory(
            user_id,
            memory_id,
        )
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Memory not found.",
        )

    return {
        "message": (
            "Memory deleted successfully."
        ),
    }


# -------------------------------------------------
# Secure file upload
# -------------------------------------------------

@app.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
):
    workspace = Path(
        settings.WORKSPACE_ROOT
    ).resolve()

    workspace.mkdir(
        parents=True,
        exist_ok=True,
    )

    original_name = Path(
        file.filename or ""
    ).name

    if not original_name:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename.",
        )

    extension = Path(
        original_name
    ).suffix.lower()

    if (
        extension
        not in settings.ALLOWED_FILE_EXTENSIONS
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"The '{extension}' file "
                "type is not supported."
            ),
        )

    target = (
        workspace / original_name
    ).resolve()

    try:
        target.relative_to(workspace)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="Invalid file path.",
        ) from error

    if target.parent != workspace:
        raise HTTPException(
            status_code=400,
            detail=(
                "Uploaded files must be placed "
                "at the workspace root."
            ),
        )

    if target.exists():
        target = workspace / (
            f"{target.stem}-"
            f"{uuid4().hex[:8]}"
            f"{target.suffix}"
        )

    written_bytes = 0

    try:
        with target.open("xb") as output:
            while True:
                chunk = await file.read(
                    64 * 1024
                )

                if not chunk:
                    break

                written_bytes += len(chunk)

                if (
                    written_bytes
                    > settings.MAX_FILE_SIZE_BYTES
                ):
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "The file exceeds the "
                            "maximum permitted size."
                        ),
                    )

                output.write(chunk)

    except Exception:
        target.unlink(
            missing_ok=True
        )

        raise

    finally:
        await file.close()

    relative_path = target.relative_to(
        workspace
    ).as_posix()

    try:
        parsed_file = (
            workspace_manager.read_file(
                relative_path
            )
        )

        if parsed_file.get(
            "format"
        ) == "text":
            content = str(
                parsed_file.get(
                    "content",
                    "",
                )
            )
        else:
            content = json.dumps(
                parsed_file,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

        content_preview = content[:12000]
        content_truncated = (
            len(content) > 12000
        )
        parse_error = None

    except Exception as error:
        logger.exception(
            "Uploaded file parsing failed"
        )

        content_preview = (
            "The file was uploaded successfully, "
            "but its contents could not be "
            "extracted automatically."
        )

        content_truncated = False
        parse_error = (
            f"{type(error).__name__}: "
            f"{error}"
        )

    return {
        "name": target.name,
        "relative_path": relative_path,
        "size": written_bytes,
        "extension": extension,
        "content": content_preview,
        "content_truncated": (
            content_truncated
        ),
        "parse_error": parse_error,
    }


# -------------------------------------------------
# Workspace browsing
# -------------------------------------------------

@app.get("/files")
async def list_workspace_files(
    path: str = Query(
        default="",
    ),
):
    try:
        return {
            "path": path,
            "items": (
                workspace_manager
                .list_directory(path)
            ),
        }

    except NotADirectoryError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


@app.get("/files/read")
async def read_workspace_file(
    path: str = Query(
        min_length=1,
    ),
):
    try:
        return workspace_manager.read_file(
            path
        )

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception(
            "Workspace file reading failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(error).__name__}: "
                f"{error}"
            ),
        ) from error


@app.get("/files/verify")
async def verify_workspace_file(
    path: str = Query(
        min_length=1,
    ),
):
    try:
        return (
            workspace_manager
            .verify_file(path)
        )

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error


# -------------------------------------------------
# Existing conversational file tools
# -------------------------------------------------

@app.post("/tools/request")
async def request_tool_operation(
    request: ToolRequest,
):
    try:
        return tool_executor.request(
            operation=request.operation,
            arguments=request.arguments,
        )

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except FileExistsError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    except (
        ValueError,
        KeyError,
    ) as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception(
            "Tool request failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(error).__name__}: "
                f"{error}"
            ),
        ) from error


@app.get("/tools/approvals")
async def list_pending_approvals():
    return (
        tool_executor
        .get_pending_approvals()
    )


@app.post(
    "/tools/approvals/"
    "{approval_id}/approve"
)
async def approve_tool_operation(
    approval_id: str,
    decision: ApprovalDecision,
):
    try:
        result = (
            tool_executor
            .approve_and_execute(
                approval_id
            )
        )

        operation = result.get(
            "operation",
            "file operation",
        )

        message = (
            f"The approved {operation} "
            "operation completed successfully."
        )

        context_manager.chat_history.add_message(
            user_id=decision.user_id,
            conversation_id=(
                decision.conversation_id
            ),
            role="assistant",
            content=message,
        )

        return {
            **result,
            "message": message,
        }

    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except FileExistsError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception(
            "Approved file operation failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(error).__name__}: "
                f"{error}"
            ),
        ) from error


@app.post(
    "/tools/approvals/"
    "{approval_id}/reject"
)
async def reject_tool_operation(
    approval_id: str,
    decision: ApprovalDecision,
):
    try:
        result = tool_executor.reject(
            approval_id
        )

        message = (
            "The proposed file operation was "
            "rejected. No file was changed."
        )

        context_manager.chat_history.add_message(
            user_id=decision.user_id,
            conversation_id=(
                decision.conversation_id
            ),
            role="assistant",
            content=message,
        )

        return {
            **result,
            "message": message,
        }

    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    except Exception as error:
        logger.exception(
            "Tool rejection failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"{type(error).__name__}: "
                f"{error}"
            ),
        ) from error