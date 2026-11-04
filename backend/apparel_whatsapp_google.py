"""Read-only Google sources using explicitly configured Apparel credentials only."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from apparel_whatsapp_brief import MAX_BYTES, read_sheet_values

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PAGES = 10
IMAGE_TYPES = {"image/jpeg", "image/png"}
FOLDER_TYPE = "application/vnd.google-apps.folder"


def _credential_info():
    raw = os.getenv("APPAREL_GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    filename = os.getenv("APPAREL_GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if not raw and not filename:
        return None
    try:
        if not raw:
            with Path(filename).open("rb") as stream:
                data = stream.read(128 * 1024 + 1)
            if len(data) > 128 * 1024:
                raise ValueError("Credential file is too large")
            raw = data.decode("utf-8")
        if len(raw.encode("utf-8")) > 128 * 1024:
            raise ValueError("Credential JSON is too large")
        payload = json.loads(raw)
        if (not isinstance(payload, dict) or payload.get("type") != "service_account"
                or payload.get("token_uri") not in {"https://oauth2.googleapis.com/token", "https://accounts.google.com/o/oauth2/token"}
                or payload.get("universe_domain", "googleapis.com") != "googleapis.com"
                or any(not payload.get(key) for key in ("client_email", "private_key", "project_id"))):
            raise ValueError("Invalid service-account key")
        return payload
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("Apparel Google credentials are invalid; configure APPAREL_GOOGLE_SERVICE_ACCOUNT_JSON or APPAREL_GOOGLE_SERVICE_ACCOUNT_FILE with an official service-account key.") from exc


def service_account_email() -> str:
    payload = _credential_info()
    return str(payload["client_email"]) if payload else ""


def get_google_credentials(scopes):
    if not set(scopes).issubset({SHEETS_SCOPE, DRIVE_SCOPE}):
        raise ValueError("Apparel brief intake permits only read-only Sheets and Drive scopes")
    payload = _credential_info()
    if payload is None:
        raise ValueError("Configure APPAREL_GOOGLE_SERVICE_ACCOUNT_JSON or APPAREL_GOOGLE_SERVICE_ACCOUNT_FILE and share the Google source with that service-account email, or upload the WhatsApp workbook instead.")
    from google.oauth2.service_account import Credentials
    try:
        return Credentials.from_service_account_info(payload, scopes=list(scopes))
    except (ValueError, TypeError) as exc:
        raise ValueError("Apparel Google service-account key could not be validated; install a valid key or upload the WhatsApp workbook instead.") from exc


def _session(scopes):
    from google.auth.transport.requests import AuthorizedSession
    return AuthorizedSession(get_google_credentials(scopes))


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", value):
        raise ValueError("Invalid Google file or spreadsheet ID")
    return value


def _url(url, host):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != host or parsed.username
            or parsed.password or parsed.port not in (None, 443)):
        raise ValueError(f"Use an HTTPS {host} URL")
    return parsed


def _sheet_id(url):
    parsed = _url(url, "docs.google.com")
    match = re.fullmatch(r"/spreadsheets/d/([A-Za-z0-9_-]{20,200})(?:/.*)?", parsed.path)
    if not match:
        raise ValueError("Use a docs.google.com/spreadsheets/d/... URL")
    return _identity(match[1])


def _drive_id(url):
    parsed = _url(url, "drive.google.com")
    match = re.fullmatch(r"/(?:drive/(?:u/\d+/)?folders|file/d)/([A-Za-z0-9_-]{20,200})(?:/.*)?", parsed.path)
    if match:
        return _identity(match[1])
    if parsed.path in {"/open", "/uc"}:
        ids = parse_qs(parsed.query).get("id", [])
        if len(ids) == 1:
            return _identity(ids[0])
    raise ValueError("Use a drive.google.com file or folder URL")


def _read_response(response, limit):
    if response.status_code in (401, 403, 404):
        email = service_account_email() or "the configured Apparel service-account email"
        raise ValueError(f"Google source is missing or access was denied. Share the sheet or Drive file/folder with {email} as a Viewer, or upload the WhatsApp workbook/image instead.")
    if not 200 <= response.status_code < 300:
        raise ValueError(f"Google source could not be read (HTTP {response.status_code}); retry later or upload the WhatsApp workbook/image instead.")
    length = response.headers.get("Content-Length")
    if length and length.isdigit() and int(length) > limit:
        raise ValueError("Google source exceeds the allowed download size")
    content = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if len(content) + len(chunk) > limit:
            raise ValueError("Google source exceeds the allowed download size")
        content.extend(chunk)
    return bytes(content)


def _get_json(session, url, params):
    with session.get(url, params=params, timeout=(10, 45), stream=True, allow_redirects=False) as response:
        data = _read_response(response, MAX_BYTES)
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Google returned an invalid source response") from exc


def read_google_brief(url, brand, *, columns=None) -> list[dict[str, str]]:
    spreadsheet_id = _sheet_id(url)
    with _session([SHEETS_SCOPE]) as session:
        payload = _get_json(session, f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}", {
            "ranges": "'WhatsApp'", "includeGridData": "true",
            "fields": "sheets(properties(title),data(startRow,startColumn,rowData(values(formattedValue,hyperlink))))",
        })
    sheets = [sheet for sheet in payload.get("sheets", []) if sheet.get("properties", {}).get("title") == "WhatsApp"]
    if len(sheets) != 1:
        raise ValueError("Google brief requires an explicitly named WhatsApp tab; upload that workbook instead.")
    values = []
    for block in sheets[0].get("data", []):
        start_row, start_column = block.get("startRow", 0), block.get("startColumn", 0)
        for offset, row in enumerate(block.get("rowData", [])):
            index = start_row + offset
            while len(values) <= index:
                values.append([])
            cells = row.get("values", [])
            needed = start_column + len(cells)
            values[index].extend([""] * max(0, needed - len(values[index])))
            for col, cell in enumerate(cells, start_column):
                values[index][col] = cell.get("hyperlink") or cell.get("formattedValue", "")
    return read_sheet_values(values, brand, f"google:{spreadsheet_id}:WhatsApp", columns=columns)


def _file_metadata(session, file_id):
    return _get_json(session, f"https://www.googleapis.com/drive/v3/files/{file_id}", {
        "fields": "id,name,mimeType,size,trashed", "supportsAllDrives": "true",
    })


def _image_record(metadata):
    if metadata.get("trashed") or metadata.get("mimeType") not in IMAGE_TYPES:
        raise ValueError("Choose a non-deleted JPEG or PNG Drive image")
    if int(metadata.get("size", 0)) > MAX_IMAGE_BYTES:
        raise ValueError("Drive image exceeds 10 MiB; upload a smaller JPEG or PNG")
    return {"id": _identity(metadata.get("id")), "name": str(metadata.get("name", "")), "mime_type": metadata["mimeType"]}


def list_google_images(url) -> list[dict[str, str]]:
    file_id = _drive_id(url)
    with _session([DRIVE_SCOPE]) as session:
        metadata = _file_metadata(session, file_id)
        if metadata.get("mimeType") != FOLDER_TYPE:
            return [_image_record(metadata)]
        if metadata.get("trashed"):
            raise ValueError("Drive folder has been deleted")
        images = []
        token = None
        for _ in range(MAX_IMAGE_PAGES):
            params = {"q": f"'{file_id}' in parents and trashed = false and (mimeType = 'image/jpeg' or mimeType = 'image/png')", "fields": "nextPageToken,files(id,name,mimeType,size,trashed)", "pageSize": 100, "orderBy": "name", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
            if token:
                params["pageToken"] = token
            payload = _get_json(session, "https://www.googleapis.com/drive/v3/files", params)
            for item in payload.get("files", []):
                if int(item.get("size", 0)) <= MAX_IMAGE_BYTES:
                    images.append(_image_record(item))
            token = payload.get("nextPageToken")
            if not token:
                return images
        raise ValueError("Drive folder has too many images; choose a smaller folder or a specific image URL")


def download_google_image(file_id) -> tuple[bytes, str, str]:
    file_id = _identity(file_id)
    with _session([DRIVE_SCOPE]) as session:
        image = _image_record(_file_metadata(session, file_id))
        with session.get(f"https://www.googleapis.com/drive/v3/files/{file_id}", params={"alt": "media", "supportsAllDrives": "true"}, timeout=(10, 45), stream=True, allow_redirects=False) as response:
            content = _read_response(response, MAX_IMAGE_BYTES)
            mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if mime != image["mime_type"]:
        raise ValueError("Drive download is not the selected JPEG or PNG image")
    if not content or not (content.startswith(b"\xff\xd8\xff") if mime == "image/jpeg" else content.startswith(b"\x89PNG\r\n\x1a\n")):
        raise ValueError("Drive download does not contain a valid JPEG or PNG image")
    filename = image["name"].replace("\\", "/").rsplit("/", 1)[-1]
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)[:255]
    return content, filename or ("image.jpg" if mime == "image/jpeg" else "image.png"), mime
