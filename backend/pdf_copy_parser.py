"""Extract selectable PDF copy only when channel and requested selection are evidenced.

PyMuPDF supplies text geometry, vector fills, font colors and annotation quads.
Images are not OCR'd, and a common card background is not selection authority.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_CHANNEL = re.compile(
    r"^(SMS|RCS|WA|WhatsApp|Email|Push(?: Notifications?)?|PN|In\s*-?\s*App)"
    r"(?:\s*[|:–—-]\s*.*)?$", re.I,
)
_GREETING = re.compile(r"^(?:dear|hi|hello|hey)\b", re.I)
_COUNT = re.compile(r"^(?:\d+\s*characters?\s*)+$", re.I)


def _channel(text: str) -> str | None:
    match = _CHANNEL.fullmatch(text.strip())
    if not match:
        return None
    value = match[1].lower()
    if value in ("wa", "whatsapp"):
        return "WA"
    if value.startswith("push") or value == "pn":
        return "PN"
    if value.startswith("in"):
        return "IN_APP"
    return value.upper()


def _colored(rgb: tuple[float, ...]) -> bool:
    # Ignore white/gray card backgrounds and dark branded text.
    return len(rgb) == 3 and max(rgb) > 0.5 and max(rgb) - min(rgb) > 0.18


def _rgb(color: int) -> tuple[float, float, float]:
    return tuple(((color >> shift) & 255) / 255 for shift in (16, 8, 0))


def _lines(page: Any, fitz: Any) -> list[dict[str, Any]]:
    result = []
    for block_index, block in enumerate(page.get_text("rawdict")["blocks"]):
        for line in block.get("lines", []):
            chars = [
                (char["c"], fitz.Rect(char["bbox"]), span["color"])
                for span in line["spans"] for char in span["chars"]
            ]
            text = "".join(char[0] for char in chars).strip()
            if text and not _COUNT.fullmatch(text):
                result.append({"text": text, "rect": fitz.Rect(line["bbox"]),
                               "chars": chars, "block": block_index})
    return result


def _copies(lines: list[dict[str, Any]], heading: dict[str, Any]) -> list[list[dict[str, Any]]]:
    body = [line for line in lines if line["rect"].y0 > heading["rect"].y1
            and line["text"].casefold() != "to whitelist"]
    starts = [line for line in body if _GREETING.match(line["text"])]
    if not starts:
        # A standalone multiline paragraph is also an explicit copy boundary.
        blocks: dict[int, list[dict[str, Any]]] = {}
        for line in body:
            blocks.setdefault(line["block"], []).append(line)
        return [part for part in blocks.values() if len(part) > 1]

    columns: list[float] = []
    for line in sorted(starts, key=lambda item: item["rect"].x0):
        x = line["rect"].x0
        if not columns or abs(x - columns[-1]) > 5:
            columns.append(x)
    result = []
    for start in sorted(starts, key=lambda item: (
        min(other["rect"].y0 for other in starts
            if abs(other["rect"].y0 - item["rect"].y0) <= 5),
        item["rect"].x0,
    )):
        x = min(columns, key=lambda value: abs(start["rect"].x0 - value))
        right = next((value - 3 for value in columns if value > x + 5), float("inf"))
        bottom = min((line["rect"].y0 for line in starts
                      if abs(line["rect"].x0 - x) <= 5
                      and line["rect"].y0 > start["rect"].y0 + 3), default=float("inf"))
        part = [line for line in body
                if x - 3 <= line["rect"].x0 < right
                and line["rect"].x1 <= right
                and start["rect"].y0 - 1 <= line["rect"].y0 < bottom]
        result.append(sorted(part, key=lambda line: (line["rect"].y0, line["rect"].x0)))
    return result


def _selection(page: Any, fitz: Any, copies: list[list[dict[str, Any]]],
               lines: list[dict[str, Any]], heading: dict[str, Any]) -> list[int]:
    page_number = page.number + 1
    drawings = page.get_drawings()
    fills = [drawing["rect"] for drawing in drawings
             if drawing.get("fill") is not None and _colored(drawing["fill"])
             and drawing.get("fill_opacity", 1) > 0
             and any(item[0] == "re" for item in drawing["items"])]
    labels = [line for line in lines if line["text"].casefold() == "to whitelist"
              and abs(line["rect"].y0 - heading["rect"].y0) <= heading["rect"].height]
    # An explicit header-band instruction applies only to this single channel section.
    if labels:
        return list(range(len(copies)))

    annotations = []
    for annotation in page.annots() or ():
        if annotation.type[0] != fitz.PDF_ANNOT_HIGHLIGHT:
            continue
        vertices = annotation.vertices or ()
        for offset in range(0, len(vertices), 4):
            quad = vertices[offset:offset + 4]
            if len(quad) == 4:
                annotations.append(fitz.Quad(quad).rect)

    selected = []
    explicit = False
    colors = set()
    for index, copy in enumerate(copies):
        total = marked = 0
        for line in copy:
            for char, rect, color in line["chars"]:
                if char.isspace():
                    continue
                total += 1
                center = (rect.tl + rect.br) / 2
                annotated = any(center in region for region in annotations)
                fill = any(center in region for region in fills)
                font = _colored(_rgb(color))
                if annotated or fill or font:
                    marked += 1
                    explicit |= annotated
                    if font:
                        colors.add(color)
        if marked and marked != total:
            raise ValueError(
                f"PDF page {page_number}: missing selection authority: highlight covers only part "
                "of a copy; confirm the complete selected SMS/card boundary."
            )
        if total and marked == total:
            selected.append(index)
    if len(colors) > 1:
        raise ValueError(f"PDF page {page_number}: missing selection authority: multiple font "
                         "highlight colors have no selection legend.")
    if not selected:
        if annotations:
            raise ValueError(f"PDF page {page_number}: missing selection authority: highlight "
                             "annotations have no geometrically associated complete copy.")
        logger.warning(
            "PDF page %s excluded: missing positive selection authority; no copy-associated "
            "highlight or explicit To Whitelist section label identifies requested content.",
            page_number,
        )
        return []
    if len(selected) == len(copies) and not explicit:
        raise ValueError(
            f"PDF page {page_number}: missing selection authority: all copies share colored "
            "formatting; a selection legend or explicit To Whitelist section label is required."
        )
    return selected


def extract_templates_from_pdf_file(
    path: str | Path, description: str = "", summary: str = "",
) -> list[dict[str, Any]]:
    """Return geometry-bounded copy items, or explain the missing source authority.

    Only explicitly headed channels are routed. An SMS-only instruction suppresses
    all other channels, even if those pages contain whitelist/highlight markers.
    Unmarked alternatives are excluded with an audit warning. A real but ambiguous
    marker raises rather than returning partial alternatives.
    """
    try:
        import pymupdf as fitz
    except ImportError as exc:
        raise ValueError("PDF extraction requires PyMuPDF>=1.24.3,<2 for text and highlight geometry.") from exc

    request = f"{description}\n{summary}"
    sms_only = bool(re.search(
        r"\b(?:pick|use|take|process|whitelist)\s+(?:only\s+)?SMS\s+(?:for now|only)\b"
        r"|\b(?:only\s+SMS|SMS[- ]only)\b", request, re.I,
    ))
    highlighted = bool(re.search(r"\bhighlight(?:ed|ing)?\b", request, re.I))
    items: list[dict[str, Any]] = []
    with fitz.open(path) as document:
        if document.needs_pass:
            raise ValueError("PDF: missing readable source authority: document requires a password.")
        for page in document:
            lines = _lines(page, fitz)
            if not lines:
                raise ValueError(f"PDF page {page.number + 1}: missing selectable text authority; "
                                 "image-only pages require an independently supplied text source.")
            if any("\ufffd" in line["text"] or "\x00" in line["text"] for line in lines):
                raise ValueError(f"PDF page {page.number + 1}: missing readable authored text authority; "
                                 "the PDF font mapping contains undecodable characters.")
            headings = [line for line in lines if _channel(line["text"])]
            if not headings:
                raise ValueError(f"PDF page {page.number + 1}: missing explicit channel heading authority.")
            channels = {_channel(line["text"]) for line in headings}
            if sms_only and "SMS" not in channels:
                continue
            if len(headings) != 1:
                raise ValueError(f"PDF page {page.number + 1}: missing unambiguous channel section geometry; "
                                 "multiple channel headings occur on the page.")
            heading = headings[0]
            channel = _channel(heading["text"])
            if channel == "IN_APP":
                continue
            copies = _copies(lines, heading)
            if not copies:
                raise ValueError(f"PDF page {page.number + 1}: missing complete selectable copy boundaries "
                                 f"for the explicit {channel} section.")
            selected = (_selection(page, fitz, copies, lines, heading) if highlighted
                        else list(range(len(copies))))
            for index in selected:
                copy = copies[index]
                # PDF line wraps are retained; no placeholder or punctuation rewriting.
                text = "\n".join(line["text"] for line in copy)
                item: dict[str, Any] = {
                    "channel": channel, "text": text, "raw_text": text,
                    "variant": f"Page {page.number + 1} Copy {index + 1}",
                    "source": f"pdf_{Path(path).stem}_p{page.number + 1}_c{index + 1}",
                    "source_page": page.number + 1,
                    "source_bbox": [min(line["rect"].x0 for line in copy),
                                    min(line["rect"].y0 for line in copy),
                                    max(line["rect"].x1 for line in copy),
                                    max(line["rect"].y1 for line in copy)],
                }
                if channel in ("WA", "RCS"):
                    # This adapter extracts text, not proven PDF-image/card associations.
                    item["media_pairing_ambiguous"] = True
                if channel == "WA":
                    # A displayed button label is not a URL; never manufacture its target.
                    if copy[-1]["text"].casefold() in ("click now", "check here"):
                        item["button_text"] = copy[-1]["text"]
                        item["text"] = "\n".join(line["text"] for line in copy[:-1])
                items.append(item)
    return items
