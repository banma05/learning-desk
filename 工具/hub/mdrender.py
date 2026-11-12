import re

import markdown

_LIST_ITEM = re.compile(r"^\s*([-*+]|\d+\.)\s")
_FENCE = re.compile(r"^\s*```")


def render_markdown(text: str) -> str:
    return markdown.markdown(_separate_lists(text), extensions=["tables", "fenced_code", "sane_lists"])


def _separate_lists(text: str) -> str:
    """Python-Markdown needs a blank line before a list; the notes often omit it."""
    out, in_fence, previous = [], False, ""
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        elif (not in_fence and _LIST_ITEM.match(line) and previous.strip()
              and not _LIST_ITEM.match(previous) and not previous.startswith(("|", ">"))):
            out.append("")
        out.append(line)
        previous = line
    return "\n".join(out)


def render_inline(text: str) -> str:
    """Render one table cell: markdown without the wrapping <p>."""
    rendered = render_markdown(text or "")
    if rendered.startswith("<p>") and rendered.endswith("</p>") and rendered.count("<p>") == 1:
        return rendered[3:-4]
    return rendered
