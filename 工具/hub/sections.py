"""Two rules shared by the skeleton and knowledge-point checks: a name's stem, and a section's extent.

A stem is what a name "is called" when names are compared: notes in （…） dropped, the part before
' — ' / '：' / ' · ', no spaces, and 和 / 及 read as 与. Two names agree when one stem contains the
other. A heading's leading number (一、 / 4. / 第 7 条) is not part of its stem.

A section runs from its heading to the next heading of the same or a higher level.
"""
import html
import re

_NOTE = re.compile(r"（[^）]*）|\([^)]*\)")
_SEPARATORS = (" — ", "：", " · ")
_SPACE = re.compile(r"\s+")
_AND = str.maketrans({"和": "与", "及": "与"})
_NUMBER = re.compile(r"^(?:第\s*[0-9一二三四五六七八九十百]+\s*[条步幕章节]\s*[：:、.．]?"
                     r"|[一二三四五六七八九十百]+[、.．]"
                     r"|[0-9]+(?:\.[0-9]+)+\s*[.、．]?|[0-9]+\s*[.、．]"
                     r"|[（(][0-9一二三四五六七八九十]+[）)]"
                     r"|[①-⑳])\s*")
_ANY_HEADING = re.compile(r"<h([1-6])\b[^>]*>")
_TAG = re.compile(r"<[^>]*>")


def _parts(name: str) -> list[str]:
    """The name cut at every separator, each part normalised; parts[0] is the stem."""
    parts = [_NOTE.sub("", name)]
    for separator in _SEPARATORS:
        parts = [piece for part in parts for piece in part.split(separator)]
    return [_SPACE.sub("", part).translate(_AND).casefold() for part in parts]


def stem(name: str) -> str:
    return _parts(name)[0]


def _unnumbered(text: str) -> str:
    return _NUMBER.sub("", text.strip(), count=1)


def heading_stem(text: str) -> str:
    return stem(_unnumbered(text))


def names_agree(name: str, target: str, heading: bool = False) -> bool:
    """A skeleton name and the title (or, with heading=True, the heading) it lands on.

    The stems are compared first. Two widenings (judgement calls):
    a name written '简称 · 说明' may agree through the part after ' · ' (the short name is the node's
    path segment, which other files refer to, so it cannot always change); and a target written
    'A：B' / 'A — B' may agree through B ("差异清单：选书与下单" is about 选书与下单).
    """
    names = [stem(name), *(stem(rest) for rest in name.split(" · ", 1)[1:])]
    targets = _parts(_unnumbered(target) if heading else target)
    return any(a and b and (a in b or b in a) for a in names for b in targets)


def find_heading(headings: list[tuple[int, str, str]], text: str) -> int | None:
    """Index of the first h2/h3 whose rendered text is text, or None."""
    return next((i for i, (_, heading, _) in enumerate(headings) if heading == text), None)


def heading_count(headings: list[tuple[int, str, str]], text: str) -> int:
    return sum(1 for _, heading, _ in headings if heading == text)


def section_span(headings: list[tuple[int, str, str]], index: int) -> tuple[int, int]:
    """(first, end) heading indexes of the section that starts at headings[index]."""
    level = headings[index][0]
    end = next((j for j in range(index + 1, len(headings)) if headings[j][0] <= level), len(headings))
    return index, end


def section_text(doc_html: str, heading_id: str) -> str:
    """Plain text of the section whose heading has this id (heading included); "" if there is none."""
    start = re.search(rf'<h([1-6]) id="{re.escape(heading_id)}"', doc_html)
    if not start:
        return ""
    level, end = int(start.group(1)), len(doc_html)
    for match in _ANY_HEADING.finditer(doc_html, start.end()):
        if int(match.group(1)) <= level:
            end = match.start()
            break
    return html.unescape(_TAG.sub("", doc_html[start.start():end]))


def mentions(text: str, words: list[str]) -> bool:
    """Whether any of words (a name and its aliases) appears in text, ignoring case and spaces."""
    folded = _SPACE.sub("", text).casefold()
    return any(word and _SPACE.sub("", word).casefold() in folded for word in words if word.strip())
