"""Pure, source-preserving SMS brief extraction and untrusted review validation."""

import csv
import hashlib
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

MAX_EXPANDED_BYTES = 80 * 1024 * 1024
MAX_CELLS = 250_000
MAX_CANDIDATES = 5_000
MAX_TEXT = 32_767
_PRE_APPROVED = r"pre(?:[^\S\r\n]*[-\u2010-\u2015\u2212\uFE58\uFE63\uFF0D][^\S\r\n]*|[^\S\r\n]+)?approved"
_TOKEN = re.compile(
    rf"\{{\{{[^{{}}\r\n]+\}}\}}|\{{#[^{{}}\r\n]+#\}}|<[^<>\r\n]+>|\[[^\[\]\r\n]+\]"
    rf"|\(\s*(?:[xX]{{2,}}|{_PRE_APPROVED})\s*\)"
    rf"|(?<![\w/@.?&#=+%:\\-]){_PRE_APPROVED}(?![\w/@?&#=+%:\\-]|\.\w)", re.IGNORECASE)
_TYPED = re.compile(r"\{#(?:num|alp|urg|uro|cbn|eml)#\}\Z")
_KINDS = {"literal", "num", "alp", "urg", "uro", "cbn", "eml"}
_LANGUAGES = {
    "english": "English", "hindi": "Hindi", "marathi": "Marathi",
    "kannada": "Kannada", "gujarati": "Gujarati", "gujrati": "Gujarati",
    "tamil": "Tamil", "telugu": "Telugu", "bengali": "Bengali",
    "punjabi": "Punjabi", "malayalam": "Malayalam",
    "urdu": "Urdu", "odia": "Odia", "oriya": "Odia", "assamese": "Assamese",
}
_SCRIPTS = {
    "Hindi": (0x0900, 0x097F), "Marathi": (0x0900, 0x097F),
    "Bengali": (0x0980, 0x09FF), "Punjabi": (0x0A00, 0x0A7F),
    "Assamese": (0x0980, 0x09FF),
    "Gujarati": (0x0A80, 0x0AFF), "Tamil": (0x0B80, 0x0BFF),
    "Telugu": (0x0C00, 0x0C7F), "Kannada": (0x0C80, 0x0CFF),
    "Malayalam": (0x0D00, 0x0D7F),
    "Urdu": (0x0600, 0x06FF), "Odia": (0x0B00, 0x0B7F),
}


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _channel(value, *, canonical=False):
    label = _norm(value)
    if len(label) > 85 or "\n" in str(value or ""):
        return ""
    if re.match(r"sms(?:\b|_)", label):
        return "sms"
    match = re.match(r"(wa|whatsapp|rcs|pn|push notification|email)(?:\b|_)", label)
    if match:
        kind = match.group(1)
        return {"wa": "whatsapp", "push notification": "pn"}.get(kind, kind) if canonical else "other"
    return ""


def _metadata(value):
    label = _norm(value)
    return bool(re.match(
        r"^(?:cta\b|link\b|date\b|time of\b|testing\b|test mobile\b|database\b|"
        r"product\b|sub product\b|campaign tag\b|notes?\b|instructions?\b|"
        r"character(?:s| count)?\b|char count\b|use\s*case\b|remark\b|base\b)", label))


def _body(value):
    """Validate source text without interpreting a declared body as a header."""
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not 1 <= len(stripped) <= MAX_TEXT:
        return False
    if stripped.startswith("="):
        return False
    if re.fullmatch(r"[\d\s+(),.;:/_-]+", stripped):
        return False
    if re.fullmatch(r"https?://\S+", stripped, re.I):
        return False
    return bool(re.search(r"[^\W\d_]", stripped, re.UNICODE))


def _copy(value):
    """Recognize unlabelled copy without promoting structural labels."""
    if not _body(value):
        return False
    stripped = value.strip()
    if _norm(stripped) in {"mentioned in base", "mentioned in database", "as per planner"}:
        return False
    label = _norm(stripped)
    if _channel(stripped) or label in _LANGUAGES or re.fullmatch(
        r"(?:normal\s+)?english|(?:hinglish|highlish)(?:\s*\+\s*witty)?", label,
    ) or label in {
        "channel", "regional", "lang", "language", "campaign", "campaign name",
        "template name", "template_name", "text", "body", "message", "content",
        "segment", "generic", "sr no", "sr no.", "template id", "header",
        "cta", "cta / link", "cta url", "link", "date", "time", "time of execution", "date & time of execution",
        "testing", "test mobile", "testing mob no", "database", "product", "sub product",
        "campaign tag", "note", "notes", "instruction", "instructions", "characters",
        "character count", "char count", "use case", "remark", "base",
    }:
        return False
    return True


def _language(value):
    label = _norm(value)
    if label in _LANGUAGES:
        return _LANGUAGES[label]
    if "hinglish" in label or "highlish" in label:
        return "Hinglish"
    if "english" in label and len(label) < 50:
        return "English"
    return ""


def _language_warnings(text, language):
    if language not in _SCRIPTS:
        return []
    expected = _SCRIPTS[language]
    counts = Counter()
    for char in text:
        if not char.isalpha():
            continue
        for _name, (start, end) in _SCRIPTS.items():
            if start <= ord(char) <= end:
                counts[(start, end)] += 1
                break
    if counts and counts.most_common(1)[0][0] != expected:
        return [f"Declared {language} language does not match the dominant source script; verify the original cell. Copy has not been changed."]
    return []


def _column(index):
    result = ""
    while index:
        index, digit = divmod(index - 1, 26)
        result = chr(65 + digit) + result
    return result


def _read_sheets(path, filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in {".xlsx", ".xls", ".csv"}:
        raise ValueError("Upload an .xlsx or .xls client brief workbook, or a .csv SMS table")
    sheets = []
    total = 0
    try:
        if Path(path).stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Client brief exceeds the 20 MiB upload limit")
        if suffix == ".csv":
            rows = []
            with open(path, encoding="utf-8-sig", newline="") as stream:
                for row in csv.reader(stream):
                    total += len(row)
                    if total > MAX_CELLS:
                        raise ValueError("CSV exceeds the safe cell extraction limit")
                    rows.append(row)
            return [(Path(filename).stem, rows)]
        if suffix == ".xlsx":
            import openpyxl

            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > 10_000 or sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
                    raise ValueError("Workbook expanded size exceeds the safe extraction limit")
            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                if len(workbook.worksheets) > 200:
                    raise ValueError("Workbook has too many worksheets")
                for sheet in workbook.worksheets:
                    if (sheet.max_row or 0) * (sheet.max_column or 0) > MAX_CELLS:
                        raise ValueError("Workbook cell dimensions exceed the safe extraction limit")
                    rows = []
                    for row in sheet.iter_rows():
                        total += len(row)
                        if total > MAX_CELLS:
                            raise ValueError("Workbook exceeds the safe cell extraction limit")
                        # Formulas without evaluated cached strings are excluded.
                        rows.append([cell.value if not (isinstance(cell.value, str) and cell.value.startswith("=")) else None for cell in row])
                    sheets.append((sheet.title, rows))
            finally:
                workbook.close()
        else:
            import xlrd

            workbook = xlrd.open_workbook(path, on_demand=True)
            try:
                if workbook.nsheets > 200:
                    raise ValueError("Workbook has too many worksheets")
                for sheet in workbook.sheets():
                    total += sheet.nrows * sheet.ncols
                    if total > MAX_CELLS:
                        raise ValueError("Workbook exceeds the safe cell extraction limit")
                    sheets.append((sheet.name, [sheet.row_values(row) for row in range(sheet.nrows)]))
            finally:
                workbook.release_resources()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Unable to read client brief workbook; upload a valid, unencrypted .xlsx or .xls file") from exc
    return sheets


def parse_brief(path: str, filename: str, *, allow_loose: bool = True) -> dict:
    """Extract SMS-scoped structures or plain message-only grids in the SMS upload context."""
    result = {"filename": filename, "sheets": [], "warnings": [], "candidates": []}
    seen = set()

    def add(sheet, row, col, text, campaign="", segment="", language="", scope="SMS", kind="channel_rows",
            template_name="", draft_fields=None):
        explicit = draft_fields is not None
        valid_text = _copy(text) if kind == "loose_cells" else _body(text)
        if not valid_text or (sheet, row, col) in seen:
            return
        if len(result["candidates"]) >= MAX_CANDIDATES:
            raise ValueError("Workbook contains too many SMS candidates; split the brief into smaller files")
        seen.add((sheet, row, col))
        cell = f"{_column(col + 1)}{row + 1}"
        digest = hashlib.sha256(f"{filename}\0{sheet}\0{cell}\0{campaign}\0{text}".encode()).hexdigest()[:12]
        label = "_".join(filter(None, [campaign or sheet, segment, language, cell]))
        ascii_label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
        from briefing_parser import detect_language

        detected = detect_language(text, language)
        language = language or {
            "en": "English", "hi": "Hindi", "mr": "Marathi", "gu": "Gujarati",
            "pa": "Punjabi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu",
            "kn": "Kannada", "ml": "Malayalam", "ur": "Urdu", "or": "Odia", "as": "Assamese",
        }.get(detected, "Regional")
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", ascii_label).strip("_").lower() or "sms"
        warnings = _language_warnings(text, language)
        if _TOKEN.search(text):
            warnings.append("Review every bracketed phrase, placeholder or pre-approved occurrence as literal text or a typed variable; no values have been invented.")
        result["candidates"].append({
            "id": f"sms_{digest}", "filename": filename, "sheet": sheet, "cell": cell, "text": text,
            "campaign": campaign, "segment": segment or sheet, "language": language,
            "scope": scope, "source_kind": kind,
            "suggested_template_name": template_name or f"sms_{safe[:43]}_{digest}",
            "suggested_template_type": "3" if "implicit" in _norm(scope) else "",
            "warnings": warnings, "variables": _TOKEN.findall(text),
            "message_type": "1" if text.isascii() else "2",
        })
        if explicit:
            result["candidates"][-1]["draft_fields"] = draft_fields

    sheets = _read_sheets(path, filename)
    mixed_channels = any(_channel(name) == "other" or any(
        _channel(value) == "other" for row in rows for value in row
    ) for name, rows in sheets)
    for name, rows in sheets:
        before = len(result["candidates"])
        normalized = _norm(name)
        if ("planner" in normalized or "calendar" in normalized or _channel(name) == "other" or _metadata(name)
                or re.fullmatch(r"cover(?:[\s_-]+(?:page|sheet))?|admin(?:istration)?|read[\s_-]*me|metadata", normalized)):
            result["warnings"].append(f"{name}: skipped non-SMS, administrative or planner worksheet.")
        elif rows and (allow_loose or _channel(name) == "sms" or any(
            _channel(value) == "sms" for row in rows for value in row
        ) or any(
            {"template id", "template message"} <= {_norm(value) for value in row}
            for row in rows
        )):
            width = max(map(len, rows), default=0)
            rows = [row + [None] * (width - len(row)) for row in rows]
            if not _template_table(name, rows, add, result["warnings"]):
                campaign_cols = sorted({c for row in rows if not any(_norm(v) == "channel" for v in row)
                                        for c, value in enumerate(row) if _norm(value) == "campaign name"})
                if campaign_cols:
                    _campaign_blocks(name, rows, campaign_cols, add)
                else:
                    if (allow_loose or _channel(name) == "sms") and (not mixed_channels or _channel(name) == "sms") and _loose_grid(rows):
                        for ri, row in enumerate(rows):
                            for ci, value in enumerate(row):
                                add(name, ri, ci, value, kind="loose_cells")
                    _channel_blocks(name, rows, add)
            if len(result["candidates"]) == before:
                if "regional" in normalized:
                    result["warnings"].append(f"{name}: ambiguous regional source has no explicit SMS channel for its message matrix; skipped rather than assuming SMS approval.")
                else:
                    result["warnings"].append(f"{name}: no explicitly scoped SMS copy found.")
            elif "regional" in normalized and any(_language(row[0]) for row in rows) and not any(_norm(row[0]) in {"lang", "language"} for row in rows):
                result["warnings"].append(f"{name}: unlabelled language-row sections outside an explicit SMS block are skipped as ambiguous/non-SMS.")
        result["sheets"].append({"name": name, "candidate_count": len(result["candidates"]) - before})
    return result


def _loose_grid(rows):
    """Only message-only grids qualify; structural labels keep their existing routing."""
    values = [value for row in rows for value in row if value is not None and str(value).strip()]
    return bool(values) and all(_copy(value) for value in values)


def _template_table(name, rows, add, warnings):
    """Explicit named SMS tables and language columns with SMS-number row labels."""
    header_row = next((ri for ri, row in enumerate(rows) if any(_norm(v) for v in row)), None)
    if header_row is None:
        return False
    headers = [re.sub(r"\s+", "_", _norm(value)) for value in rows[header_row]]
    body_col = next((c for c, header in enumerate(headers)
                     if header in {"text", "body", "message", "template_message"} or re.fullmatch(r"sms(?:_\d+)?", header)), None)
    if body_col is not None and ("template_name" in headers or (
        "template_id" in headers and headers[body_col] == "template_message"
    )):
        name_col = headers.index("template_name") if "template_name" in headers else None
        for ri in range(header_row + 1, len(rows)):
            row = rows[ri]
            fields = dict(zip(headers, row, strict=False))
            if fields.get("channel") and _channel(fields["channel"]) != "sms":
                warnings.append(f"{name}!{_column(body_col + 1)}{ri + 1}: non-SMS/unrecognized channel row excluded.")
                continue
            template_name = str(row[name_col] or "").strip() if name_col is not None else ""
            language = _language(fields.get("language")) or str(fields.get("language") or "")
            if not language:
                codes = {"eng": "English", "mar": "Marathi", "kan": "Kannada", "hin": "Hindi",
                         "tam": "Tamil", "tel": "Telugu", "ben": "Bengali", "guj": "Gujarati"}
                language = next((codes[token] for token in re.split(r"[^a-z]+", template_name.lower()) if token in codes), "")
            add(name, ri, body_col, row[body_col], language=language, kind="template_table",
                template_name=template_name, draft_fields=fields)
        return True
    languages = {c: _language(value) for c, value in enumerate(rows[header_row]) if _language(value)}
    if headers[0] not in {"sr_no", "sr_no.", "sr._no.", "sr._no"} or not languages:
        return False
    for ri in range(header_row + 1, len(rows)):
        row = rows[ri]
        if not re.fullmatch(r"sms\s*\d+", _norm(row[0])):
            continue
        for c, language in languages.items():
            add(name, ri, c, row[c], campaign=str(row[0]), language=language, kind="sms_language_matrix")
    return True


def _campaign_blocks(name, rows, anchors, add):
    """Each label/value block owns its channel, campaign and continuation state."""
    width = len(rows[0])
    for index, anchor in enumerate(anchors):
        end = anchors[index + 1] if index + 1 < len(anchors) else width
        columns = list(range(anchor + 1, end))
        scopes = {c: name if _channel(name) == "sms" else "" for c in columns}
        campaigns = {}
        segment = ""
        active = False
        for ri, row in enumerate(rows):
            label = _norm(row[anchor])
            channel = _channel(row[anchor])
            if channel:
                for c in columns:
                    if label not in {"sms text", "sms utility"} or not scopes[c]:
                        scopes[c] = str(row[anchor]) if channel == "sms" else ""
                active = channel == "sms"
                # Side-by-side variants may override a shared label column's scope.
                for c in columns:
                    if _channel(row[c]):
                        scopes[c] = str(row[c]) if _channel(row[c]) == "sms" else ""
                if label not in {"sms text", "sms utility"}:
                    continue
            if label == "campaign name":
                campaigns = {c: str(row[c]) for c in columns if row[c] is not None}
                active = any(scopes.values())
                continue
            if _metadata(row[anchor]):
                active = False
                continue
            if label and not channel and not re.fullmatch(r"c\d+|[a-z]", label):
                active = False
                if len(label) < 60:
                    segment = str(row[anchor])
                continue
            if active:
                for c in columns:
                    if scopes.get(c):
                        add(name, ri, c, row[c], campaigns.get(c, ""), segment, "", scopes[c], "campaign_block")


def _channel_blocks(name, rows, add):
    width = len(rows[0])
    # Explicit per-channel body columns may coexist with a generic Channel column.
    for header_row, row in enumerate(rows):
        if not any(_norm(value) in {"channel", "template name", "campaign name", "language", "lang"} for value in row):
            continue
        sms_columns = [c for c, value in enumerate(row) if _channel(value) == "sms"
                       and re.search(r"\b(?:text|content|body|message)\b", _norm(value))]
        if sms_columns:
            for ri in range(header_row + 1, len(rows)):
                for c in sms_columns:
                    add(name, ri, c, rows[ri][c], kind="channel_columns")
            break
    # Language rows with channel columns (Lang | SMS | WA | PN).
    matrix_header = next((ri for ri, row in enumerate(rows)
                          if _norm(row[0]) in {"lang", "language"} and any(_channel(v) == "sms" for v in row[1:])), None)
    if matrix_header is not None:
        channels = {}
        for ri, row in enumerate(rows):
            if _norm(row[0]) in {"lang", "language"}:
                channels = {c: str(v) for c, v in enumerate(row) if _channel(v) == "sms"}
                continue
            language = _language(row[0])
            if language:
                for c, scope in channels.items():
                    add(name, ri, c, row[c], language=language, scope=scope, kind="language_matrix")
            elif any(v is not None for v in row):
                channels = {}
        return

    # Channel headers declare columns; their body headings are never row-label anchors.
    anchors = {c for row in rows for c, value in enumerate(row) if _norm(value) == "channel"}
    for row in rows:
        if any(_norm(value) == "channel" for value in row):
            continue
        anchors.update(c for c, value in enumerate(row) if (
            _norm(value) == "content" and c + 1 < width and _channel(row[c + 1])
        ) or (_channel(value) and c + 1 < width and any(_copy(r[c + 1]) for r in rows)))
    anchors = sorted(anchors)
    # One neighbour may be independent; multiple agreeing labels establish a shared row.
    shared_scopes = []
    for row in rows:
        peers = [str(row[c]) for c in anchors if _norm(row[c])]
        shared_scopes.append(peers[0] if len(peers) >= 2 and _channel(peers[0])
                             and len({_channel(value, canonical=True) for value in peers}) == 1 else "")
    for index, anchor in enumerate(anchors):
        end = anchors[index + 1] if index + 1 < len(anchors) else width
        content_columns = {anchor + 1: ""} if anchor + 1 < end else {}
        variants = {}
        campaign_column = None
        segment_column = None
        scope = ""
        segment = ""
        for ri, row in enumerate(rows):
            label = _norm(row[anchor])
            if label == "content" and anchor + 1 < end and _channel(row[anchor + 1]):
                scope = str(row[anchor + 1]) if _channel(row[anchor + 1]) == "sms" else ""
                content_columns = {anchor + 1: ""}
                continue
            # Repeated language/variant headers replace, rather than merge, the old map.
            is_header = label in {"channel", "regional"} and any(row[c] is not None for c in range(anchor + 1, end))
            if is_header:
                content_columns = {}
                variants = {}
                campaign_column = None
                segment_column = None
                for c in range(anchor + 1, end):
                    header = _norm(row[c])
                    language = _language(row[c])
                    if header in {"campaign", "campaign name"}:
                        campaign_column = c
                    if header in {"segment", "usecase", "use case"}:
                        segment_column = c
                    is_variant = bool(re.fullmatch(r"[a-z]", header) or re.match(
                        r"(?:scenario|variant)\s*(?:\d+|[a-z])\b", header,
                    ))
                    if is_variant:
                        variants[c] = str(row[c])
                    if language or header in {"content", "copy", "text", "body", "message", "sms text", "sms content"} or is_variant:
                        content_columns[c] = language
                scope = ""
                continue
            row_scope = row[anchor] if label else shared_scopes[ri]
            channel = _channel(row_scope)
            if channel:
                scope = str(row_scope) if channel == "sms" else ""
            elif label and not re.fullmatch(r"c\d+", label):
                # Unknown row labels, including language labels after PN, end the block.
                scope = ""
                if len(label) < 60 and not _metadata(row[anchor]):
                    segment = str(row[anchor])
                continue
            if scope:
                for c, language in content_columns.items():
                    row_segment = str(row[segment_column]) if segment_column is not None and row[segment_column] is not None else segment
                    row_segment = " / ".join(filter(None, [row_segment, variants.get(c, "")]))
                    campaign = str(row[campaign_column]) if campaign_column is not None and row[campaign_column] is not None else ""
                    add(name, ri, c, row[c], campaign=campaign, segment=row_segment, language=language, scope=scope)
            elif not label and ri == 0:
                headings = [str(row[c]) for c in range(anchor + 1, end)
                            if isinstance(row[c], str) and not _metadata(row[c]) and len(row[c]) < 60]
                if headings:
                    segment = headings[0]


def validate_brief_review(brief: object, text: str) -> list[str]:
    """Validate review evidence without trusting client metadata or rewriting final copy."""
    if not isinstance(brief, dict):
        return ["Brief review must be an object"]
    errors = []
    original = brief.get("original_text")
    if not isinstance(original, str) or not original.strip() or len(original) > MAX_TEXT:
        errors.append("Brief original_text must be nonempty source copy within the workbook cell limit")
        original = ""
    sources = brief.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_CANDIDATES:
        errors.append("Brief review requires nonempty source references")
    else:
        for source in sources:
            if not isinstance(source, dict) or any(not isinstance(source.get(key), str) or len(source[key]) > 500
                                                     for key in ("sheet", "cell", "campaign", "segment", "language")):
                errors.append("Brief source references must contain string sheet, cell, campaign, segment and language fields")
                break
            if not source["sheet"].strip() or not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", source["cell"]):
                errors.append("Brief source references require a worksheet and valid cell coordinate")
                break
    warnings = brief.get("warnings")
    if not isinstance(warnings, list) or len(warnings) > MAX_CANDIDATES or any(not isinstance(w, str) or len(w) > MAX_TEXT for w in warnings):
        errors.append("Brief warnings must be a list of strings")
    decisions = brief.get("variables")
    tokens = _TOKEN.findall(original)
    literals = Counter()
    if not isinstance(decisions, list) or len(decisions) != len(tokens):
        errors.append("Brief variable decisions must match every original token in occurrence order")
    else:
        for index, (token, decision) in enumerate(zip(tokens, decisions, strict=True), 1):
            if not isinstance(decision, dict) or decision.get("token") != token:
                errors.append(f"Brief variable decision {index} does not match its original source token")
                continue
            kind = decision.get("kind")
            sample = decision.get("sample")
            if not isinstance(kind, str) or kind not in _KINDS:
                errors.append(f"Resolve brief token {index} as literal text or a typed variable")
            if not isinstance(sample, str) or len(sample) > 2000:
                errors.append(f"Brief token {index} sample must be a string within 2000 characters")
            elif isinstance(kind, str) and kind in _KINDS - {"literal"} and not sample.strip():
                errors.append(f"Provide an explicit sample for brief token {index}")
            if kind == "literal":
                literals[token] += 1
    if brief.get("acknowledged") is not True:
        errors.append("Acknowledge the reviewed source, variable choices and final SMS copy")
    if not isinstance(text, str):
        errors.append("Final brief SMS text must be a string")
    else:
        unresolved = Counter(token for token in _TOKEN.findall(text) if not _TYPED.fullmatch(token))
        if any(count > literals[token] for token, count in unresolved.items()):
            errors.append("Final SMS contains unresolved bracketed or legacy tokens not explicitly reviewed as literal text")
    return errors
