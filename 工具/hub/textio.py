from pathlib import Path


def read_text(path: Path) -> str:
    """Decode as UTF-8 (BOM tolerated), falling back to GBK for files saved as ANSI by Notepad."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("gbk")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")
