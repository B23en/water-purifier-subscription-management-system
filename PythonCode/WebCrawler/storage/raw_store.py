from pathlib import Path
from typing import Any
import json

ALLOWED_RAW_EXTENSIONS = {".json", ".txt"}

def save_raw_file(save_path: Path, content: bytes) -> str:
    if save_path.suffix not in ALLOWED_RAW_EXTENSIONS:
        raise ValueError("File extension must be .json or .txt")

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(content)
    return str(save_path)

def save_raw_json(save_path: Path, payload: dict[str, Any]) -> str:
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return save_raw_file(save_path, content)


def save_raw_text(save_path: Path, text: str) -> str:
    return save_raw_file(save_path, text.encode("utf-8"))