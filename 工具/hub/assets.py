import base64
import hashlib
import html
import os
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from .errors import FormatError

_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".gif": "image/gif"}
_UNTOUCHED = re.compile(r"^(https?:|mailto:|data:|#)", re.IGNORECASE)
_WINDOWS_ABS = re.compile(r"^[A-Za-z]:[/\\]")


class AssetBook:
    """Rewrites links in rendered HTML: embeds images, turns local .md into in-page docs."""

    def __init__(self, code_root: Path):
        self.code_root = code_root.resolve()
        self.errors: list[FormatError] = []
        self._images: dict[str, str] = {}
        self._pending: dict[Path, None] = {}
        self._rendered: set[Path] = set()
        self._sections: dict[Path, str] = {}
        self._backlinks: dict[Path, set[Path]] = {}

    def backlinks(self, path: Path) -> list[Path]:
        """Files whose rendered HTML linked to the .md file at path."""
        return sorted(self._backlinks.get(path.resolve(), set()))

    def anchor_for(self, path: Path) -> str:
        """In-page href for a local file: its mapped section, else its doc page."""
        section = self._section_of(path.resolve())
        return f"#{section}" if section else f"#doc-{self.register_doc(path)}"

    def map_section(self, path: Path, section: str) -> None:
        """Links to path (a file, or anything under a directory) jump to a page section instead."""
        self._sections[path.resolve()] = section

    def _section_of(self, target: Path) -> str | None:
        for path, section in self._sections.items():
            if target == path or target.is_relative_to(path):
                return section
        return None

    def register_doc(self, path: Path) -> str:
        rel = path.resolve().relative_to(self.code_root).as_posix()
        return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]

    def mark_rendered(self, path: Path) -> None:
        self._rendered.add(path.resolve())

    def pending_docs(self) -> list[Path]:
        return [p for p in self._pending if p not in self._rendered]

    def images(self) -> dict[str, str]:
        return dict(self._images)

    def rewrite(self, html_text: str, from_file: Path, attachment: bool = False) -> str:
        tags = _TagFinder.find(html_text)
        out, cursor = [], 0
        for start, end, name, attrs in tags:
            out.append(html_text[cursor:start])
            out.append(self._rewrite_tag(name, attrs, from_file, attachment) or html_text[start:end])
            cursor = end
        out.append(html_text[cursor:])
        return "".join(out)

    def _rewrite_tag(self, name: str, attrs: dict, from_file: Path, attachment: bool) -> str | None:
        key = "src" if name == "img" else "href"
        url = attrs.get(key)
        if not url or _UNTOUCHED.match(url):
            return None
        target = self._resolve(url, from_file)
        if name == "a" and target.suffix.lower() == ".md":
            self._backlinks.setdefault(target, set()).add(from_file.resolve())
        if not target.exists():
            self.errors.append(FormatError(from_file.name, 0, f"文件不存在：{url}"))
            attrs["class"] = "broken"
        elif name == "a" and (section := self._section_of(target)):
            attrs["href"] = f"#{section}"
        elif target.suffix.lower() in _MIME and target.is_file():
            image_id = self._embed(target)
            if name == "img":
                attrs["src"] = self._images[image_id]
            else:
                attrs.update({"href": "#", "data-img": image_id})
        elif target.suffix.lower() == ".md" and target.is_file() and self._inside_root(target) and not attachment:
            attrs["href"] = f"#doc-{self.register_doc(target)}"
            self._pending.setdefault(target, None)
        else:
            attrs[key] = _file_url(target)
        return _build_tag(name, attrs)

    def _resolve(self, url: str, from_file: Path) -> Path:
        path = unquote(url.split("#", 1)[0])
        base = Path(path) if _WINDOWS_ABS.match(path) else from_file.parent / path
        return Path(os.path.normpath(base)).resolve()

    def _inside_root(self, path: Path) -> bool:
        return path.is_relative_to(self.code_root)

    def _embed(self, image: Path) -> str:
        if image.suffix.lower() == ".png" and image.with_suffix(".svg").is_file():
            image = image.with_suffix(".svg")
        image_id = "img-" + hashlib.sha1(str(image).encode("utf-8")).hexdigest()[:10]
        if image_id not in self._images:
            data = base64.b64encode(image.read_bytes()).decode("ascii")
            self._images[image_id] = f"data:{_MIME[image.suffix.lower()]};base64,{data}"
        return image_id


def _file_url(path: Path) -> str:
    posix = path.as_posix()
    for raw, encoded in (("%", "%25"), (" ", "%20"), ("#", "%23"), ("?", "%3F")):
        posix = posix.replace(raw, encoded)
    return "file:///" + posix


def _build_tag(name: str, attrs: dict) -> str:
    parts = [name] + [f'{k}="{html.escape(v, quote=True)}"' for k, v in attrs.items()]
    return "<" + " ".join(parts) + ">"


class _TagFinder(HTMLParser):
    """Collects (start, end, name, attrs) of <img> and <a> start tags."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self._line_starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self._line_starts.append(i + 1)
        self.tags = []

    @classmethod
    def find(cls, text: str):
        finder = cls(text)
        finder.feed(text)
        finder.close()
        return finder.tags

    def handle_starttag(self, tag, attrs):
        if tag not in ("img", "a"):
            return
        line, col = self.getpos()
        start = self._line_starts[line - 1] + col
        raw = self.get_starttag_text()
        self.tags.append((start, start + len(raw), tag, {k: v or "" for k, v in attrs}))

    handle_startendtag = handle_starttag
