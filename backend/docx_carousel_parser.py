"""Read inline-image RCS carousel briefs without flattening their card boundaries."""

import hashlib
import logging
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from cta import resolve_cta_url
from jira_client import MEDIA_CACHE_DIR

logger = logging.getLogger(__name__)
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_FIELD = re.compile(r"^(title|description|body|cta)\s*:\s*(.*)$", re.I)
_URL = re.compile(r"https?://[^\s<>]+|<link>|\{\{[^{}]+\}\}", re.I)
_TERMS = re.compile(r"^T\s*&\s*Cs?\b", re.I)
_CAROUSEL_HEADING = re.compile(r"RCS\s+carou(?:sel|sal)(?:\s+\d+)?\s*:?", re.I)


def _xml(archive: ZipFile, member: str) -> ET.Element:
    info = archive.getinfo(member)
    if info.file_size > 8 * 1024 * 1024:
        raise ValueError("DOCX XML part exceeds size limit")
    data = archive.read(info)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("DOCX XML declarations are not supported")
    return ET.fromstring(data)  # nosec B314  # nosemgrep


def _visible_nodes(node: ET.Element):
    """Select one compatibility branch and exclude deleted/moved-away content."""
    if node.tag in {_W + "del", _W + "moveFrom"}:
        return
    if node.tag == _MC + "AlternateContent":
        branch = node.find(_MC + "Choice")
        if branch is None:
            branch = node.find(_MC + "Fallback")
        if branch is not None:
            yield from _visible_nodes(branch)
        return
    yield node
    for child in node:
        yield from _visible_nodes(child)


def _paragraph(node: ET.Element) -> tuple[str, list[str | None], bool]:
    parts = []
    images = []
    floating = False
    for child in _visible_nodes(node):
        if child.tag == _W + "t":
            parts.append(child.text or "")
        elif child.tag == "{http://schemas.microsoft.com/office/word/2015/wordml/symex}symEx":
            value = child.get("{http://schemas.microsoft.com/office/word/2015/wordml/symex}char", "")
            codepoint = int(value, 16)
            if not 0 <= codepoint <= 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                raise ValueError("DOCX extended symbol is not a Unicode scalar")
            parts.append(chr(codepoint))
        elif child.tag in {_W + "br", _W + "cr"}:
            # A page break is pagination, not an authored copy line break.
            if child.get(_W + "type") != "page":
                parts.append("\n")
        elif child.tag == _W + "tab":
            parts.append("\t")
        elif child.tag == _W + "noBreakHyphen":
            parts.append("‑")
        elif child.tag == _W + "softHyphen":
            parts.append("\u00ad")
        elif child.tag == _A + "blip":
            images.append(child.get(_R + "embed"))
        elif child.tag == _WP + "anchor":
            floating = True
    return "".join(parts).strip(), images, floating


def _section_heading(node: ET.Element, text: str) -> bool:
    if not text or _FIELD.match(text) or "\n" in text:
        return False
    style = node.find(f"{_W}pPr/{_W}pStyle")
    if style is not None and style.get(_W + "val", "").lower().startswith("heading"):
        return True
    alignment = node.find(f"{_W}pPr/{_W}jc")
    runs = [run for run in node.findall(_W + "r") if run.find(_W + "t") is not None]
    return bool(
        alignment is not None
        and alignment.get(_W + "val") == "center"
        and runs
        and all(
            (bold := run.find(f"{_W}rPr/{_W}b")) is not None
            and bold.get(_W + "val", "1") not in {"0", "false", "off"}
            for run in runs
        )
    )


def _save_image(archive: ZipFile, relationship: ET.Element | None) -> str | None:
    if relationship is None or relationship.get("TargetMode", "").lower() == "external":
        return None
    if not relationship.get("Type", "").endswith("/image"):
        return None
    target = unquote(relationship.get("Target", ""))
    parsed = urlsplit(target)
    member = PurePosixPath("word") / target
    if (
        parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
        or "\\" in target or target.startswith("/") or ".." in member.parts
        or not member.as_posix().startswith("word/media/")
    ):
        return None
    suffix = member.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return None
    name = member.as_posix()
    infos = [info for info in archive.infolist() if info.filename == name]
    if len(infos) != 1 or not 0 < infos[0].file_size <= 20 * 1024 * 1024:
        return None
    data = archive.read(infos[0])
    destination = MEDIA_CACHE_DIR / f"jira_docx_{hashlib.sha256(data).hexdigest()}{suffix}"
    MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Replace the directory entry atomically, never follow an existing cache symlink.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=MEDIA_CACHE_DIR, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(destination)


def _card(block: dict, archive: ZipFile, relationships: dict) -> dict | None:
    fields = {"title": [], "description": [], "cta": [], "copy": []}
    mode = "copy"
    cta_count = 0
    for paragraph in block["paragraphs"]:
        for line in paragraph.splitlines():
            match = _FIELD.match(line.strip())
            if match:
                mode = match[1].lower()
                if mode == "body":
                    mode = "description"
                if mode == "cta":
                    cta_count += 1
                if match[2]:
                    fields[mode].append(match[2])
            elif _TERMS.match(line.strip()):
                fields["description"].append(line)
            elif line.strip():
                fields[mode].append(line)
    if cta_count != 1:
        return None
    title = "\n".join(fields["title"]).strip()
    copy = fields["copy"]
    if copy and not title:
        # Only an authored line/paragraph boundary separates implicit title and body.
        title = copy[0] if len(copy) > 1 else ""
        copy = copy[1:] if title else copy
    description = "\n".join([*copy, *fields["description"]]).strip()
    if not description:
        return None
    cta = "\n".join(fields["cta"]).strip()
    urls = list(_URL.finditer(cta))
    button_url = resolve_cta_url(urls[0][0], "tata") if len(urls) == 1 else None
    label = _URL.sub("", cta).strip()
    if label.startswith("[") and label.endswith("]"):
        label = label[1:-1].strip()
    media = None
    if len(block["images"]) == 1 and not block["floating"]:
        try:
            media = _save_image(archive, relationships.get(block["images"][0]))
        except (OSError, KeyError, ValueError, BadZipFile) as exc:
            logger.warning("Could not extract DOCX card image: %s", exc)
    return {
        "card_title": title,
        "card_description": description,
        "media_url": media,
        "media_filename": Path(media).name if media else None,
        "button_text": label or None,
        "button_url": button_url,
        "suggestions": [{
            "suggestionType": "url_action", "text": label,
            "postbackData": label, "url": button_url,
        }] if label and button_url else [],
    }


def extract_docx_carousels(path: str | Path) -> list[dict] | None:
    """Return RCS carousels, None for ordinary Word, [] for unsafe/empty structure.

    Inline drawings delimit cards; authored headings delimit separate carousels.
    Floating drawings retain copy but cannot authorize a media pairing. Tables are
    not linear card evidence and are deliberately not flattened into this format.
    """
    path = Path(path)
    recognized = False
    try:
        with ZipFile(path) as archive:
            recognized = bool(re.search(r"carou(?:sel|sal)", path.stem, re.I)) and bool(
                re.search(r"(?:^|[^a-z])rcs(?:$|[^a-z])", path.stem, re.I)
            )
            root = _xml(archive, "word/document.xml")
            body = root.find(_W + "body")
            if body is None:
                return [] if recognized else None
            paragraphs = [(node, *_paragraph(node)) for node in body if node.tag == _W + "p"]
            context = path.stem + "\n" + "\n".join(text for _, text, _, _ in paragraphs)
            recognized = recognized or bool(re.search(r"carou(?:sel|sal)", context, re.I)) and bool(
                re.search(r"(?:^|[^a-z])rcs(?:$|[^a-z])", context, re.I)
            )
            if not recognized:
                return None
            if body.find(".//" + _W + "tbl") is not None:
                logger.warning("DOCX carousel %s excluded: table-based card grouping and image authority are unsupported", path)
                return []
            relationships = {}
            if "word/_rels/document.xml.rels" in archive.namelist():
                for relationship in _xml(archive, "word/_rels/document.xml.rels"):
                    key = relationship.get("Id")
                    # Duplicate IDs cannot prove a unique image relationship.
                    relationships[key] = relationship if key not in relationships else None
            groups = []
            blocks = []
            current = None
            section = "Carousel"
            for node, text, images, floating in paragraphs:
                if (_section_heading(node, text) or _CAROUSEL_HEADING.fullmatch(text)) and not images:
                    if current is not None:
                        blocks.append(current)
                        current = None
                    if blocks:
                        groups.append((section, blocks))
                        blocks = []
                    section = text
                    continue
                if images:
                    if current is not None and current["paragraphs"]:
                        blocks.append(current)
                        current = None
                    if current is None:
                        current = {"paragraphs": [], "images": [], "floating": False}
                    current["images"].extend(images)
                    current["floating"] |= floating
                elif text:
                    if current is None:
                        current = {"paragraphs": [], "images": [], "floating": False}
                    has_cta = any(re.search(r"(?:^|\n)CTA\s*:", p, re.I) for p in current["paragraphs"])
                    # A new title/body after a finished CTA has no image authority.
                    if has_cta and not _TERMS.match(text) and not _FIELD.match(text) and current["paragraphs"][-1].strip().lower() != "cta:":
                        blocks.append(current)
                        current = {"paragraphs": [], "images": [], "floating": False}
                    elif has_cta and re.match(r"title\s*:", text, re.I):
                        blocks.append(current)
                        current = {"paragraphs": [], "images": [], "floating": False}
                if text and current is not None:
                    current["paragraphs"].append(text)
            if current is not None:
                blocks.append(current)
            if blocks:
                groups.append((section, blocks))
            items = []
            for index, (section, blocks) in enumerate(groups, 1):
                cards = [_card(block, archive, relationships) for block in blocks]
                # Never silently collapse an incomplete carousel into a partial one.
                if len(cards) < 2 or any(card is None for card in cards):
                    logger.warning(
                        "DOCX carousel %s section %r excluded: fewer than two cards or missing unambiguous card copy/CTA boundaries",
                        path, section,
                    )
                    continue
                first = cards[0]
                items.append({
                    "channel": "RCS", "template_type": "carousel", "variant": section,
                    "title": first["card_title"], "card_title": first["card_title"],
                    "text": first["card_description"],
                    "raw_text": "\n---\n".join("\n".join(block["paragraphs"]) for block in blocks),
                    "button_text": first["button_text"], "button_url": first["button_url"],
                    "media_file": first["media_url"], "media_filename": first["media_filename"],
                    "media_pairing_ambiguous": any(not card["media_url"] for card in cards),
                    "carousel_cards": cards, "source": f"docx_carousel_{path.name}_{index}",
                })
            return items
    except (OSError, KeyError, ValueError, ET.ParseError, BadZipFile) as exc:
        logger.warning("Could not read DOCX carousel %s: %s", path, exc)
        return [] if recognized else None
