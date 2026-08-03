FILE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List files and directories inside the permitted "
                "workspace. Paths are relative to the workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative directory path. Use an empty "
                            "string for the workspace root."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a UTF-8 text or code file from the permitted "
                "workspace before answering questions or editing it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Relative file path inside the workspace."
                        ),
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": (
                "Search filenames and supported text file contents "
                "inside the permitted workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                    },
                    "search_content": {
                        "type": "boolean",
                        "default": True,
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 30,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_info",
            "description": (
                "Get metadata for a file in the permitted workspace."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create a new text/code file or replace an existing "
                "file. This operation requires user approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                    "content": {
                        "type": "string",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "default": False,
                    },
                },
                "required": [
                    "path",
                    "content",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace exactly one matching section in an existing "
                "text/code file. Read the file first. This operation "
                "requires user approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                    "old_text": {
                        "type": "string",
                        "description": (
                            "Exact existing text to replace."
                        ),
                    },
                    "new_text": {
                        "type": "string",
                        "description": (
                            "Replacement text."
                        ),
                    },
                },
                "required": [
                    "path",
                    "old_text",
                    "new_text",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_file",
            "description": (
                "Rename or move a file within the permitted workspace. "
                "This operation requires user approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                    },
                    "destination": {
                        "type": "string",
                    },
                },
                "required": [
                    "source",
                    "destination",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": (
                "Move a file from the permitted workspace to the "
                "Windows Recycle Bin. This operation requires explicit "
                "user approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    }
                },
                "required": ["path"],
            },
        },
    },
]