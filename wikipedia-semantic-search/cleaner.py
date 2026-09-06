"""Wikitext cleaning utilities shared by the parser and search service.

Converts MediaWiki wikitext to readable plain text:
- Removes templates ({{...}}, nested), refs (<ref>), comments, tables, gallery
- Resolves [[links]] to display text, strips '''bold'''/''italic'' markup
- Handles external links, file/category links, list markers, indentation
"""

import re

# --- HTML-ish constructs -----------------------------------------------------

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_REF_FULL_RE = re.compile(r"<ref[^>]*>.*?</ref>", re.S)
_REF_EMPTY_RE = re.compile(r"<ref[^/>]*/>")
_GALLERY_RE = re.compile(r"<gallery[^>]*>.*?</gallery>", re.S)
_MATH_RE = re.compile(r"<math[^>]*>.*?</math>", re.S)
_OTHER_TAGS_RE = re.compile(r"</?(?:br|hr|small|big|sup|sub|center|div|span|blockquote|nowiki|noinclude|includeonly|onlyinclude|syntaxhighlight|chem|score)[^>]*>", re.I)

# --- wiki markup -------------------------------------------------------------

# External links [http://... label] or [http://...]
_EXT_LINK_RE = re.compile(r"\[(?:https?|ftp)://[^\s\]]+(?:\s+([^\]]+))?\]")
_ITALIC_BOLD_RE = re.compile(r"'{2,5}")
_HEADING_RE = re.compile(r"^={1,6}\s*(.*?)\s*={1,6}\s*$", re.M)
_LIST_MARKER_RE = re.compile(r"^[ \t]*[:*#;]+", re.M)
_TABLE_LINE_RE = re.compile(r"^[ \t]*\{\|[^\n]*|^[ \t]*\|[+-]?[ \t]*$|^[ \t]*\|\}[^\n]*|^[ \t]*![ \t]*$", re.M)
_TABLE_CELL_SEP_RE = re.compile(r"\|\||!!")
_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _remove_templates(text: str) -> str:
    """Remove {{...}} template invocations including nested braces.

    Uses a character scanner with depth counting (regex can't handle nesting).
    """
    out = []
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("{{", i):
            depth += 1
            i += 2
            continue
        if text.startswith("}}", i) and depth > 0:
            depth -= 1
            i += 2
            continue
        if depth == 0:
            out.append(text[i])
        i += 1
    return "".join(out)


def _resolve_internal_link(match: re.Match) -> str:
    """[[Target|Display]] -> Display, [[Target]] -> Target."""
    inner = match.group(1)
    # [[a|b|c]] — display is the last segment
    parts = inner.split("|")
    display = parts[-1].strip()
    return display


# Link types whose entire [[...]] should be dropped (not resolved to text)
_DROP_LINK_PREFIXES = ("File:", "Image:", "Media:", "Category:",
                       "Wikipedia:", "Help:", "Template:", "Portal:", "Talk:")


def _last_top_level_pipe(inner: str) -> int:
    """Index of the last '|' not inside a nested [[...]], or -1."""
    depth = 0
    last = -1
    i = 0
    n = len(inner)
    while i < n:
        if inner.startswith("[[", i):
            depth += 1
            i += 2
        elif inner.startswith("]]", i):
            depth = max(0, depth - 1)
            i += 2
        else:
            if inner[i] == "|" and depth == 0:
                last = i
            i += 1
    return last


def _remove_links(text: str) -> str:
    """Depth-aware [[...]] handling: supports nested links and drops
    File/Category/... links entirely.

    Wikitext allows [[Outer [[inner|text]] tail]] — we scan with a bracket
    counter, then recurse into the display segment to resolve nested links
    and only split on pipes at the top bracket level (an inner link's pipe
    must not be treated as the outer link's display separator).
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("[[", i):
            depth = 1
            j = i + 2
            while j < n - 1 and depth > 0:
                if text.startswith("[[", j):
                    depth += 1
                    j += 2
                elif text.startswith("]]", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            if depth == 0:
                inner = text[i + 2 : j - 2]
                stripped = inner.strip()
                lowered = stripped.lower()
                if any(lowered.startswith(p.lower()) for p in _DROP_LINK_PREFIXES):
                    pass  # drop entirely
                else:
                    # display = text after last TOP-LEVEL pipe (recursively cleaned)
                    pipe = _last_top_level_pipe(stripped)
                    display = stripped[pipe + 1 :].strip() if pipe != -1 else stripped
                    display = _remove_links(display)
                    if display:
                        out.append(display)
                i = j
                continue
            # unterminated [[ — skip the opener, continue scanning
            out.append("[")
            i += 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _resolve_external_link(match: re.Match) -> str:
    """[http://... label] -> label, [http://...] -> ''"""
    return match.group(1).strip() if match.group(1) else ""


def clean_wikitext(text: str) -> str:
    """Convert wikitext to clean plain text."""
    if not text:
        return ""
    t = text
    t = _COMMENT_RE.sub("", t)
    t = _GALLERY_RE.sub("", t)
    t = _MATH_RE.sub("", t)
    # Templates BEFORE refs: a malformed <ref> without </ref> would otherwise
    # swallow a '{{' (leaving its '}}' behind) and break brace balance,
    # leaking infobox bodies into intros. Removing templates first makes the
    # ref regexes safe.
    t = _remove_templates(t)
    t = _REF_FULL_RE.sub("", t)
    t = _REF_EMPTY_RE.sub("", t)
    t = _OTHER_TAGS_RE.sub("", t)
    t = _remove_links(t)
    t = _EXT_LINK_RE.sub(_resolve_external_link, t)
    t = _ITALIC_BOLD_RE.sub("", t)
    t = _TABLE_LINE_RE.sub("", t)
    t = _TABLE_CELL_SEP_RE.sub(" | ", t)
    t = _HEADING_RE.sub(r"\1", t)
    t = _LIST_MARKER_RE.sub("", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<") \
         .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    t = _WS_RE.sub(" ", t)
    t = _MULTI_NL_RE.sub("\n\n", t)
    # Drop orphaned link brackets left by template removal inside links —
    # any legitimate [[...]] was already resolved above.
    t = t.replace("[[", "").replace("]]", "")
    return t.strip()


def extract_intro(wikitext: str, max_chars: int = 2000) -> str:
    """Extract and clean the lead section (text before the first == heading)."""
    idx = wikitext.find("\n==")
    intro = wikitext[:idx] if idx != -1 else wikitext
    cleaned = clean_wikitext(intro)
    # intros can still be long on messy pages — truncate at paragraph boundary
    if len(cleaned) > max_chars:
        cut = cleaned[:max_chars]
        last_nl = cut.rfind("\n")
        last_dot = cut.rfind(". ")
        boundary = max(last_nl, last_dot)
        if boundary > max_chars * 0.6:
            cut = cut[: boundary + 1]
        cleaned = cut
    return cleaned.strip()


def split_paragraphs(clean_text: str, min_len: int = 30) -> list[str]:
    """Split cleaned article text into paragraphs for evidence extraction."""
    return [p.strip() for p in clean_text.split("\n\n") if p.strip() and len(p.strip()) >= min_len]


def clean_full_text(wikitext: str, max_chars: int = 12000) -> str:
    """Clean full article text, truncated to max_chars for LLM evidence use."""
    cleaned = clean_wikitext(wikitext)
    return cleaned[:max_chars]
