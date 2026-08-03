from pathlib import Path

from files.adapters import (
    BinaryAdapter,
    ExcelAdapter,
    PdfAdapter,
    PowerPointAdapter,
    TextAdapter,
    WordAdapter,
)
from files.base_adapter import FileAdapter


TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".py", ".dart", ".html", ".htm", ".css",
    ".scss", ".sass", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx",
    ".json", ".jsonl", ".yaml", ".yml", ".xml", ".sql", ".php",
    ".java", ".kt", ".kts", ".c", ".h", ".cpp", ".hpp", ".cs",
    ".go", ".rs", ".rb", ".sh", ".ps1", ".bat", ".toml", ".ini",
    ".cfg", ".csv", ".tsv", ".env", ".gitignore", ".dockerignore",
    ".vue", ".svelte", ".swift", ".r", ".tex", ".graphql", ".gql",
    ".gradle", ".properties", ".lock", ".ipynb", ".svg",
}


class AdapterRegistry:
    def __init__(self, max_text_bytes: int = 5 * 1024 * 1024):
        self.text = TextAdapter(max_bytes=max_text_bytes)
        self.binary = BinaryAdapter()
        self._structured: dict[str, FileAdapter] = {
            ".docx": WordAdapter(),
            ".xlsx": ExcelAdapter(),
            ".xlsm": ExcelAdapter(),
            ".pptx": PowerPointAdapter(),
            ".pdf": PdfAdapter(),
        }

    def get(self, path: Path) -> FileAdapter:
        extension = path.suffix.lower()
        if extension in TEXT_EXTENSIONS or path.name.lower() in {
            "dockerfile", "makefile", "license", "readme"
        }:
            return self.text
        return self._structured.get(extension, self.binary)

    def is_semantically_editable(self, path: Path) -> bool:
        return not isinstance(self.get(path), BinaryAdapter)

    @property
    def supported_extensions(self) -> list[str]:
        return sorted(TEXT_EXTENSIONS | set(self._structured))
