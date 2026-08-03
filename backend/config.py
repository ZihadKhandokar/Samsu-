import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


class Settings:
    # -------------------------------------------------
    # llama.cpp
    # -------------------------------------------------

    LLAMA_BASE_URL = os.getenv(
        "LLAMA_BASE_URL",
        "http://127.0.0.1:8080",
    )

    # This must match llama-server --alias.
    LLAMA_MODEL = os.getenv(
        "LLAMA_MODEL",
        "samsu-local",
    )

    # -------------------------------------------------
    # Database
    # -------------------------------------------------

    DATABASE_PATH = os.getenv(
        "DATABASE_PATH",
        str(BASE_DIR / "assistant.db"),
    )

    AGENT_CHECKPOINT_PATH = os.getenv(
        "AGENT_CHECKPOINT_PATH",
        str(BASE_DIR / "agent_checkpoints.db"),
    )

    # -------------------------------------------------
    # Assistant behavior
    # -------------------------------------------------

    SYSTEM_PROMPT = os.getenv(
        "SYSTEM_PROMPT",
        """
You are Samsu++, a local AI software-development assistant.

For ordinary questions, answer clearly and directly.

For software-building requests:

1. Do not provide only a basic example, demonstration, outline,
   or incomplete starter unless the user explicitly requests one.

2. Determine the requested architecture, database schema, API,
   frontend, validation, security, and project structure.

3. Produce complete, runnable code with correct filenames,
   imports, configuration, error handling, and setup commands.

4. When file tools are available and the user asks to build or
   save a project, work directly in the permitted workspace.

5. Read existing files before editing them. Preserve compatible
   existing code unless a replacement is necessary.

6. Divide large applications into coherent phases. Complete every
   file in the current phase instead of returning shortened or
   placeholder code.

7. Never use placeholders such as "implement this later",
   "add your logic here", or "...".

8. Do not claim that an application is complete until its required
   files have been created and verified.

9. If the complete application cannot fit in one response, finish
   one runnable phase and clearly identify the next phase.

10. For PHP projects, use PDO prepared statements, password_hash,
    secure sessions, CSRF protection, validation, and proper HTTP
    response codes.

11. For MySQL schemas, include foreign keys, indexes, constraints,
    timestamps, and appropriate deletion behavior.

12. For Canvas-style applications, consider the editor, document
    persistence, version history, previews, AI edits,
    authentication, exports, and real-time communication.

13. When the user clearly asks to create, edit, rename, save, or
    delete a file, use the available file tools. Do not only
    describe the proposed operation.

14. Do not ask for confirmation in ordinary chat text. Submit the
    file operation and allow the application's approval interface
    to request approval.

15. Do not say a file was created, edited, deleted, renamed, or
    saved until a successful tool result confirms the operation.

16. For large multi-file projects, create a complete file plan,
    request approval once, and then continue generating, saving,
    and verifying the approved files.

17. Keep every file operation inside the permitted workspace.
    Never use absolute paths supplied by the model or access files
    outside the workspace.

Be implementation-oriented, precise, safe, and thorough.
""".strip(),
    )

    # -------------------------------------------------
    # Model generation
    # -------------------------------------------------

    MAX_CONTEXT_TOKENS = int(
        os.getenv(
            "MAX_CONTEXT_TOKENS",
            "3500",
        )
    )

    MAX_RESPONSE_TOKENS = int(
        os.getenv(
            "MAX_RESPONSE_TOKENS",
            "4096",
        )
    )

    TEMPERATURE = float(
        os.getenv(
            "TEMPERATURE",
            "0.7",
        )
    )

    # -------------------------------------------------
    # File workspace
    # -------------------------------------------------

    # Samsu++ may only create, read, edit, rename, or
    # delete files inside this directory.
    WORKSPACE_ROOT = os.getenv(
        "WORKSPACE_ROOT",
        str(PROJECT_DIR / "workspace"),
    )

    # Compatibility with the existing file manager,
    # upload endpoint, and tool executor.
    FILE_WORKSPACE_ROOT = WORKSPACE_ROOT

    MAX_FILE_SIZE_BYTES = int(
        os.getenv(
            "MAX_FILE_SIZE_BYTES",
            str(25 * 1024 * 1024),
        )
    )

    # -------------------------------------------------
    # Supported uploads and text/source formats
    # -------------------------------------------------

    ALLOWED_FILE_EXTENSIONS = {
        # Plain text and documentation
        ".txt",
        ".md",
        ".rst",
        ".tex",

        # Office documents and PDF
        ".docx",
        ".xlsx",
        ".xlsm",
        ".pptx",
        ".pdf",

        # Data files
        ".csv",
        ".tsv",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".xml",

        # Configuration files
        ".toml",
        ".ini",
        ".cfg",
        ".env",
        ".properties",
        ".lock",

        # Database files and scripts
        ".sql",

        # Web development
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".jsx",
        ".tsx",
        ".vue",
        ".svelte",
        ".svg",
        ".php",

        # Python and notebooks
        ".py",
        ".ipynb",

        # Flutter and Dart
        ".dart",

        # Java and Kotlin
        ".java",
        ".kt",
        ".kts",
        ".gradle",

        # C, C++, and C#
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",

        # Additional languages
        ".go",
        ".rs",
        ".rb",
        ".swift",
        ".r",

        # Shell and PowerShell
        ".sh",
        ".ps1",
        ".bat",

        # API and query languages
        ".graphql",
        ".gql",
    }


settings = Settings()