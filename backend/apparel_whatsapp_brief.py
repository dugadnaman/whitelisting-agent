"""Offline, transposed Apparel WhatsApp brief intake; never supplies campaign defaults."""
from __future__ import annotations

import calendar
import csv
import io
import json
import re
import posixpath
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile
MAX_BYTES = 5 * 1024 * 1024
BRANDS = {"VS", "Aldo", "BBW", "CIS", "Crocs", "R&B", "CK", "AGIPL"}
IST = timezone(timedelta(hours=5, minutes=30))


def _text(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value is None else str(value)


def _identifier(value):
    text = _text(value).strip()
    while text and (text[0].isspace() or unicodedata.category(text[0]) == "Cf"):
        text = text[1:]
    while text and (text[-1].isspace() or unicodedata.category(text[-1]) == "Cf"):
        text = text[:-1]
    return text


def _label(value):
    return re.sub(r"[^a-z0-9]", "", _text(value).lower())


def _column(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _date_parts(text):
    text = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", text, flags=re.I)
    match = re.search(r"\b(\d{1,2})\s*([A-Za-z]+)\s*(\d{4})?", text)
    if not match:
        raise ValueError("Expected an explicit day and month")
    months = {name.lower(): i for i in range(1, 13) for name in (calendar.month_name[i], calendar.month_abbr[i])}
    month = months.get(match[2].lower())
    if not month:
        raise ValueError("Unrecognized month")
    return int(match[1]), month, int(match[3]) if match[3] else None


def _date(text, year):
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text
    day, month, explicit_year = _date_parts(_text(text))
    if explicit_year is None and year is None:
        raise ValueError("Send date requires an explicit year in brief or tracking dates")
    return date(explicit_year or year, month, day)


def tracking_window(text, scheduled_at) -> dict[str, str]:
    """Return elapsed tracking duration, rejecting absent or nonpositive windows."""
    start = datetime.fromisoformat(scheduled_at) if isinstance(scheduled_at, str) else scheduled_at
    if not isinstance(start, datetime):
        raise ValueError("Tracking requires a scheduled timestamp")
    raw = _identifier(text)
    duration = re.fullmatch(r"(\d+)\s*(hours?|hrs?|days?)", raw, re.I)
    if duration:
        value = int(duration[1])
        unit = "hours" if duration[2].lower().startswith("h") else "days"
        end = start + (timedelta(hours=value) if unit == "hours" else timedelta(days=value))
    else:
        parts = re.split(r"\s*(?:–|—|\bto\b|-)\s*", raw, flags=re.I)
        if len(parts) != 2:
            raise ValueError("Tracking requires positive hours/days or an explicit date range")
        first = _date_parts(parts[0])
        last = _date_parts(parts[1])
        first_year = first[2] or last[2] or start.year
        # An explicit end year anchors an otherwise yearless December start.
        if first[2] is None and last[2] and first[1] > last[1]:
            first_year -= 1
        last_year = last[2] or first_year + (last[1] < first[1])
        begin_date = date(first_year, first[1], first[0])
        end_date = date(last_year, last[1], last[0])
        value = (end_date - begin_date).days
        unit = "days"
        start = datetime.combine(begin_date, start.timetz())
        end = datetime.combine(end_date, start.timetz())
    if value <= 0:
        raise ValueError("Tracking duration must be positive")
    return {"tracking_start": start.isoformat(), "tracking_end": end.isoformat(), "tracking_value": str(value), "tracking_unit": unit}


FIELDS = {
    "owner": "owner", "briefdate": "brief_date", "senddateandday": "send_date",
    "senddate": "send_date", "sendtime": "send_time", "campaignname": "campaign_name",
    "trackthegoalfornoofhoursdays": "tracking", "senderidwhatsappnumber": "whatsapp_sender",
    "senderid": "whatsapp_sender", "whatsappnumber": "whatsapp_sender", "templateid": "whatsapp_template_id",
    "templatetype": "template_type", "targetaudienceinclude": "segment_name", "include": "segment_name",
    "targetaudience": "segment_name", "exclude": "exclude_segment_name",
    "bodycopyifvariables": "whatsapp_variable_instructions", "ifvariables": "whatsapp_variable_instructions",
    "bodycopy": "whatsapp_variable_instructions", "imageurl": "whatsapp_image_url",
    "ctalink": "cta_raw", "globalcontrolgroup": "global_control_group", "notes": "notes",
    "campaignid": "existing_campaign_id", "campaignstatus": "existing_campaign_status",
}

CAMPAIGN_FIELDS = {
    "campaign_name", "whatsapp_sender", "whatsapp_template_id", "segment_name",
    "exclude_segment_name", "whatsapp_variable_instructions", "whatsapp_image_url",
    "cta_raw", "existing_campaign_id",
}


def _ctas(raw):
    if not raw.strip():
        return ""
    result = {}
    pending = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.fullmatch(r"(.+?):\s*(https?://\S+)", line)
        if match:
            label, url = match.groups()
        elif line.startswith(("https://", "http://")) and pending:
            label, url = pending, line
            pending = None
        elif line.endswith(":"):
            if pending:
                raise ValueError("CTA label has no URL")
            pending = line[:-1].strip()
            continue
        else:
            raise ValueError("CTA requires a label and explicit URL")
        if not label or label in result:
            raise ValueError("CTA labels must be nonempty and unique")
        result[label] = url
    if pending:
        raise ValueError("CTA label has no URL")
    return json.dumps(result, ensure_ascii=False)


def read_sheet_values(values, brand, source_ref, *, sheet="WhatsApp", columns=None):
    if brand not in BRANDS:
        raise ValueError("Unknown Apparel brand")
    if sheet != "WhatsApp" and "whatsapp" not in sheet.lower():
        return []
    values = list(values)
    selected = {str(column).upper() for column in columns} if columns is not None else None
    width = max((len(row) for row in values), default=0)
    rows = []
    for index in range(2, width):
        physical = _column(index + 1)
        if selected is not None and physical not in selected:
            continue
        fields = {}
        for cells in values:
            value = cells[index] if len(cells) > index else None
            labels = [_label(cell) for cell in cells[:2]]
            field = next((FIELDS[label] for label in ["".join(labels), *reversed(labels)] if label in FIELDS), None)
            if field:
                fields[field] = _text(value)
        if not any(fields.get(key, "").strip() for key in CAMPAIGN_FIELDS):
            continue
        row = {key: "" for key in ("campaign_name", "segment_name", "exclude_segment_name", "whatsapp_sender", "whatsapp_template_id", "template_type", "scheduled_at", "tracking_goal", "whatsapp_variable_instructions", "whatsapp_name_fallback", "whatsapp_image_url", "whatsapp_cta_links", "existing_campaign_id", "existing_campaign_status", "global_control_group", "notes")}
        row.update(fields)
        row["tracking_goal"] = fields.get("tracking", "")
        row.update(account="apparel", channel="WHATSAPP", brand=brand, source_ref=_text(source_ref), row_id=f"{sheet}!{physical}", timezone="Asia/Kolkata")
        for key in ("campaign_name", "segment_name", "exclude_segment_name", "whatsapp_sender", "whatsapp_template_id", "existing_campaign_id", "existing_campaign_status"):
            row[key] = _identifier(row[key])
        warnings = []
        for key in ("campaign_name", "segment_name", "whatsapp_sender", "whatsapp_template_id"):
            if not row[key]:
                warnings.append(f"Missing {key}")
        try:
            years = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", fields.get("brief_date", "") + " " + fields.get("tracking", ""))
            send_date = _date(fields.get("send_date", ""), int(years[0]) if years else None)
            if _date_parts(fields.get("send_date", ""))[2] is None and fields.get("brief_date"):
                brief_day, brief_month, brief_year = _date_parts(fields["brief_date"])
                if brief_year and (send_date.month, send_date.day) < (brief_month, brief_day):
                    send_date = send_date.replace(year=brief_year + 1)
            raw_time = fields.get("send_time", "").strip()
            parsed_time = None
            for fmt in ("%I:%M%p", "%I:%M %p", "%H:%M:%S", "%H:%M", "%I%p"):
                try:
                    parsed_time = datetime.strptime(raw_time.upper(), fmt).time()
                    break
                except ValueError:
                    pass
            if parsed_time is None:
                raise ValueError("Missing or invalid send time")
            row["scheduled_at"] = datetime.combine(send_date, parsed_time, IST).isoformat()
        except (ValueError, TypeError) as exc:
            warnings.append(str(exc))
        if brand not in {"Crocs", "AGIPL", "R&B", "CK"}:
            try:
                row.update(tracking_window(row["tracking_goal"], row["scheduled_at"]))
            except (ValueError, TypeError) as exc:
                warnings.append(str(exc))
        try:
            row["whatsapp_cta_links"] = _ctas(fields.get("cta_raw", ""))
        except ValueError as exc:
            warnings.append(str(exc))
        # Preserve instructions verbatim; only extract an explicitly stated fallback.
        instructions = row["whatsapp_variable_instructions"].translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'}))
        fallback = re.search(r"(?:fallback\s*(?:is|:|=)?\s*[\"']?([\w -]+)|[\"']([^\"']+)[\"']\s+(?:as\s+)?fallback)", instructions, re.I)
        if fallback:
            row["whatsapp_name_fallback"] = (fallback[1] or fallback[2]).strip()
        else:
            missing_name = re.search(r"\bname\b.*?\b(?:can't|cannot|isn't|is not|not)\b.*?\b(?:found|available)\b.*?\buse\s+(?:the\s+)?(?:copy|text)\s*[-:–—]?\s*[\"']([^\"']+)[\"']", instructions, re.I | re.S)
            if missing_name:
                row["whatsapp_name_fallback"] = missing_name[1]
        if warnings:
            row["_row_warnings"] = "; ".join(warnings)
        rows.append(row)
    return rows


def _xlsx_links(data):
    """Read only WhatsApp's OOXML hyperlinks; read-only openpyxl omits them."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    relation = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 64 * 1024 * 1024:
                raise ValueError("Expanded workbook exceeds 64 MiB")
            document = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            sheet = next((node for node in document.iter(ns + "sheet") if node.get("name") == "WhatsApp"), None)
            if sheet is None:
                raise ValueError("Brief requires a WhatsApp worksheet")
            relations = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            target = next(node.get("Target", "") for node in relations if node.get("Id") == sheet.get(relation))
            path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
            if not path.startswith("xl/worksheets/"):
                raise ValueError("Invalid WhatsApp worksheet relationship")
            relpath = posixpath.dirname(path) + "/_rels/" + posixpath.basename(path) + ".rels"
            if relpath not in archive.namelist():
                return {}
            targets = {node.get("Id"): node.get("Target") for node in ElementTree.fromstring(archive.read(relpath))
                       if node.get("TargetMode") == "External" and node.get("Type", "").endswith("/hyperlink")}
            links = {}
            with archive.open(path) as source:
                for _, element in ElementTree.iterparse(source, events=("end",)):
                    if element.tag == ns + "hyperlink" and element.get(relation) in targets:
                        links[element.get("ref")] = targets[element.get(relation)]
                    element.clear()
            return links
    except (BadZipFile, KeyError, StopIteration, ElementTree.ParseError):
        raise ValueError("Invalid XLSX WhatsApp brief") from None


def read_brief(filename, data, brand, *, source_ref=None, columns=None):
    if len(data) > MAX_BYTES:
        raise ValueError("Brief exceeds 5 MiB")
    suffix = Path(filename).suffix.lower()
    reference = source_ref if source_ref is not None else filename
    if suffix == ".csv":
        values = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
        return read_sheet_values(values, brand, reference, columns=columns)
    if suffix != ".xlsx":
        raise ValueError("Only XLSX or transposed CSV briefs are supported")
    import openpyxl
    links = _xlsx_links(data)
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    try:
        if "WhatsApp" not in workbook.sheetnames:
            raise ValueError("Brief requires a WhatsApp worksheet")
        worksheet = workbook["WhatsApp"]
        if (worksheet.max_row or 0) > 512 or (worksheet.max_row or 0) * (worksheet.max_column or 0) > 1_000_000:
            raise ValueError("WhatsApp brief dimensions are too large")
        values = []
        for number, cells in enumerate(worksheet.iter_rows(), 1):
            row = [cell.value for cell in cells]
            labels = [_label(value) for value in row[:2]]
            field = next((FIELDS[label] for label in ["".join(labels), *reversed(labels)] if label in FIELDS), None)
            if field in {"cta_raw", "whatsapp_image_url"}:
                for index, cell in enumerate(cells[2:], 2):
                    text = _text(cell.value).strip()
                    target = links.get(f"{_column(index + 1)}{number}")
                    if target and not re.search(r"https?://", text):
                        row[index] = f"{text.rstrip(':')}: {target}" if field == "cta_raw" and text else target
            values.append(row)
        return read_sheet_values(values, brand, reference, columns=columns)
    finally:
        workbook.close()
