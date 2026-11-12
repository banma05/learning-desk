"""Per-knowledge-base settings read from 学习台配置.json.

Every problem degrades to the default for that one setting plus a format hint: a broken
config must never stop the page from being built or a hook from running.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import FormatError
from .textio import read_text

CONFIG_FILE = "学习台配置.json"
DEFAULT_PREFIXES = (("T", "技术"), ("B", "业务"), ("Q", "思考"), ("L", "学习方法"))
_PREFIX = re.compile(r"^[A-Z]$")


@dataclass(frozen=True)
class Config:
    askers: tuple[str, ...] = ()  # empty: questions are not split by who to ask
    prefixes: tuple[tuple[str, str], ...] = DEFAULT_PREFIXES
    code_root: Path | None = None  # None: the folder that holds the knowledge base


def load_config(root: Path) -> tuple[Config, list[FormatError]]:
    path = root / CONFIG_FILE
    if not path.exists():
        return Config(), [_hint("没有 学习台配置.json，按默认值处理")]
    try:
        data = json.loads(read_text(path))
        if not isinstance(data, dict):
            raise ValueError("顶层应为对象")
    except ValueError as exc:
        return Config(), [_hint(f"读不出来，按默认值处理：{exc}")]
    errors: list[FormatError] = []
    return Config(askers=_askers(data, errors), prefixes=_prefixes(data, errors),
                  code_root=_code_root(data, root, errors)), errors


def _askers(data: dict, errors: list) -> tuple[str, ...]:
    value = data.get("问谁", [])
    if isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value):
        return tuple(v.strip() for v in value)
    errors.append(_hint("问谁应为文字列表，按不分问谁处理"))
    return ()


def _prefixes(data: dict, errors: list) -> tuple[tuple[str, str], ...]:
    if "问题编号前缀" not in data:
        return DEFAULT_PREFIXES
    value = data["问题编号前缀"]
    if (isinstance(value, dict) and value
            and all(isinstance(k, str) and _PREFIX.match(k) and isinstance(v, str) for k, v in value.items())):
        return tuple(value.items())
    errors.append(_hint('问题编号前缀应为 {"T": "技术"} 这样的对照，按默认值处理'))
    return DEFAULT_PREFIXES


def _code_root(data: dict, root: Path, errors: list) -> Path | None:
    if "代码根目录" not in data:
        return None
    value = data["代码根目录"]
    path = (root / value).resolve() if isinstance(value, str) and value.strip() else None
    if path is None or not path.is_dir():
        errors.append(_hint("代码根目录不存在，按知识库的上一级处理"))
        return None
    return path


def _hint(message: str) -> FormatError:
    return FormatError(CONFIG_FILE, 0, message)
