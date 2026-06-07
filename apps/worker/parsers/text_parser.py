from pathlib import Path


def parse_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")
