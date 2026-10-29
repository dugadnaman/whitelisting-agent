"""Tata Capital SMS DLT registration through an encrypted VILPOWER portal session.

Portal contract verified October 2026: inventory and option searches use POST;
only contentAdd registers anything. Never automatically replay a registration POST.
"""

import re
from datetime import date, datetime, timedelta
from functools import cache
from html import unescape
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urljoin, urlparse

import requests

from models import ApprovalStatus, SubmissionResult, SubmissionStatus

BASE_URL = "https://www.vilpower.in"
TATA_ENTITY_ID = "1101637310000019220"
TATA_ENTITY_NAME = "TATA CAPITAL LIMITED"
_ADD = "/content_templates/contentAdd/"
_INDEX = "/content_templates/contentIndex/"
_INVENTORY = "/content_templates/contentTemplateJson/"
_VARIABLE = re.compile(r"\{#(num|alp|urg|uro|cbn|eml)#\}")
_SAMPLE_PATTERNS = {
    "num": r"[0-9]{1,40}",
    "cbn": r"[0-9]{3,14}",
    "urg": r"(?i:https?://|www\.)[^\r\n]{1,116}",
    "uro": r"(?i:https?://|www\.)[^\r\n]{1,116}",
    "eml": r"[^\s@]{1,38}@[^\s@]{1,38}\.[^\s@]{1,38}",
    "alp": r"(?:(?!(?i:https?|www))[^<>]){1,40}",
}


class VilpowerUnavailable(RuntimeError):
    """Portal data could not be verified; never interpret this as empty inventory."""


class VilpowerAuthExpired(VilpowerUnavailable):
    """The operator must refresh their Tata VILPOWER session."""


class _HTML(HTMLParser):
    """Only the portal fields we consume; credentials/scripts are never exported."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.text = []
        self.inputs = []
        self.selects = {}
        self.labels = {}
        self.divs = []
        self.errors = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.stack and self.stack[-1][0] == "div":
            self.stack[-1][1]["_has_children"] = True
        if tag == "br":
            self.handle_data("\n")
        if tag == "input":
            self.inputs.append(attrs)
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            return
        self.stack.append((tag, attrs, []))
        if tag == "select":
            self.selects.setdefault(attrs.get("name", ""), [])

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if index is None:
            return
        closed = self.stack[index:]
        del self.stack[index:]
        for name, attrs, parts in reversed(closed):
            text = "".join(parts)
            if name == "option":
                select = next((a.get("name", "") for t, a, _ in reversed(self.stack) if t == "select"), "")
                if attrs.get("value"):
                    self.selects.setdefault(select, []).append({"id": attrs["value"], "text": text.strip()})
            if name == "label":
                self.labels[attrs.get("for", "")] = text.strip()
            if name == "div" and not attrs.get("_has_children"):
                self.divs.append(" ".join(text.split()))
            if set(attrs.get("class", "").split()) & {"errorlist", "error", "alert-danger", "invalid-feedback"} and text.strip():
                self.errors.append(" ".join(text.split()))

    def handle_data(self, data):
        if any(tag in {"script", "style"} for tag, _, _ in self.stack):
            return
        self.text.append(data)
        for _, _, parts in self.stack:
            parts.append(data)

    def value(self, name):
        return next((a.get("value", "") for a in self.inputs if a.get("name") == name), "")


def _plain(value):
    # Do not strip whitespace: CRLF, punctuation and leading/trailing spaces matter.
    return "".join(_HTML(str(value or "")).text)


def _content(value):
    # Only remove the known display wrapper. Literal tags in SMS text are data.
    text = str(value or "")
    wrapped = re.fullmatch(r"""<span\b[^>]*class=["']break-all["'][^>]*>(.*)</span>""", text, re.DOTALL)
    if wrapped:
        text = wrapped[1]
    return unescape(re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE))


def _scope(client):
    if client != "tata":
        raise ValueError("SMS DLT whitelisting is supported only for Tata Capital")


def _credentials(client, credentials):
    _scope(client)
    if credentials is None:
        from portal_sessions import load_session
        credentials = load_session(client, "sms")
    if not isinstance(credentials, dict) or not credentials.get("cookie"):
        raise VilpowerAuthExpired("Configure the Tata Capital VILPOWER portal session in Settings")
    if credentials.get("entity_id") != TATA_ENTITY_ID or credentials.get("provider", "vilpower") != "vilpower":
        raise VilpowerUnavailable("Saved SMS credentials do not identify Tata Capital on VILPOWER")
    return credentials


class _Portal:
    def __init__(self, credentials):
        cookie = credentials.get("cookie", "")
        if not isinstance(cookie, str) or not cookie.strip() or not cookie.isascii() or "\r" in cookie or "\n" in cookie:
            raise ValueError("Supply a single VILPOWER Cookie header value")
        cookie = cookie.strip()
        if cookie.lower().startswith("cookie:"):
            cookie = cookie[7:].strip()
        parsed = SimpleCookie()
        try:
            parsed.load(cookie)
        except Exception:
            raise ValueError("Invalid VILPOWER Cookie header") from None
        if not parsed.get("sessionid"):
            raise ValueError("VILPOWER Cookie header must contain sessionid")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Karix-Tata-DLT/1.0", "Referer": BASE_URL + _INDEX})
        for key, morsel in parsed.items():
            self.session.cookies.set(key, morsel.value, domain=urlparse(BASE_URL).hostname, path="/")
        self.entity_id = credentials.get("entity_id", "")

    def close(self):
        self.session.close()

    def request(self, method, path, **kwargs):
        try:
            response = self.session.request(method, BASE_URL + path, timeout=(10, 60), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise VilpowerUnavailable("VILPOWER did not return a verifiable response") from None
        location = response.headers.get("Location", "")
        target = urlparse(urljoin(BASE_URL + path, location))
        if response.status_code in {401, 403} or (300 <= response.status_code < 400 and ("login" in target.path.lower() or target.path == "/")):
            raise VilpowerAuthExpired("VILPOWER session expired; refresh the Tata Capital session in Settings")
        if 300 <= response.status_code < 400:
            if method == "POST" and path == _ADD and target.netloc == urlparse(BASE_URL).netloc and target.path == _INDEX:
                return response
            raise VilpowerUnavailable("VILPOWER returned an unexpected redirect")
        if response.status_code != 200:
            raise VilpowerUnavailable("VILPOWER returned an unsuccessful response")
        if "<" in response.text[:100]:
            page = _HTML(response.text)
            if any(a.get("type") == "password" for a in page.inputs) and "/logout/" not in response.text:
                raise VilpowerAuthExpired("VILPOWER session expired; refresh the Tata Capital session in Settings")
        return response

    def identity(self):
        page = _HTML(self.request("GET", "/accountsettings/profile").text)
        matches = set()
        for text in page.divs:
            match = re.fullmatch(r"(.+?)\s*\|\s*([0-9]{19})", text)
            if match:
                matches.add((match[1].strip(), match[2]))
        if matches != {(TATA_ENTITY_NAME, TATA_ENTITY_ID)} or self.entity_id != TATA_ENTITY_ID:
            raise VilpowerUnavailable("Live VILPOWER principal entity does not match Tata Capital and the supplied entity ID")

    def form(self):
        page = _HTML(self.request("GET", _ADD).text)
        if not page.value("csrfmiddlewaretoken") or not page.selects.get("iCategoryID"):
            raise VilpowerUnavailable("VILPOWER registration form could not be verified")
        return page

    def json(self, path, data, csrf):
        response = self.request("POST", path, data=data, headers={"X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest"})
        try:
            result = response.json()
        except ValueError:
            raise VilpowerUnavailable("VILPOWER returned invalid inventory or option data") from None
        if isinstance(result, dict) and (result.get("error_text") or result.get("error")):
            raise VilpowerUnavailable("VILPOWER could not load the requested inventory or options")
        return result

    def inventory(self, search=""):
        csrf = self.form().value("csrfmiddlewaretoken")
        server_search = search if len(search) >= 4 or search.isdigit() else ""

        def window(first, last, length=1000):
            data = {"draw": "1", "start": "0", "length": str(length)}
            data.update({f"data[{k}]": v for k, v in {
                "Template": server_search, "status": "-1", "header": "", "templateStatus": "-1",
                "from_date": first.isoformat(), "to_date": last.isoformat(), "lob": "",
            }.items()})
            result = self.json(_INVENTORY, data, csrf)
            if not isinstance(result, dict) or not isinstance(result.get("aaData"), list):
                raise VilpowerUnavailable("VILPOWER inventory format changed")
            try:
                count = int(result["iTotalDisplayRecords"])
            except (KeyError, TypeError, ValueError):
                raise VilpowerUnavailable("VILPOWER inventory count is missing") from None
            batch = [_normalize(row) for row in result["aaData"]]
            if count < len(batch) or (count and not batch):
                raise VilpowerUnavailable("VILPOWER returned incomplete inventory")
            return count, batch

        def requested_day(item):
            try:
                return datetime.strptime(item["requested_at"].split()[0], "%d-%b-%Y").date()
            except (ValueError, IndexError, AttributeError, TypeError):
                raise VilpowerUnavailable("VILPOWER inventory requested date could not be verified") from None

        # Offset paging is unsafe: the portal ignores order parameters and ties
        # in RequestedDate repeat/skip rows across pages. Page by disjoint dates
        # instead, proving each complete partition against the server's counts.
        total, batch = window(date.min, date.max)
        count, last = total, date.max
        rows, seen = [], set()

        def append_complete(items):
            for item in items:
                if item["template_id"] in seen:
                    raise VilpowerUnavailable("VILPOWER inventory contains overlapping records; reload it")
                seen.add(item["template_id"])
                rows.append(item)

        while count > len(batch):
            pivot = min(requested_day(item) for item in batch)
            older_count, older = window(date.min, pivot)
            cutoff = pivot
            if older_count == count:
                # A day's bulk registrations can exceed the normal page size.
                cutoff = pivot - timedelta(days=1) if pivot > date.min else None
                older_count, older = window(date.min, cutoff) if cutoff else (0, [])
            newer_count = count - older_count
            if not 0 < newer_count <= count:
                raise VilpowerUnavailable("VILPOWER inventory changed during date pagination; reload it")
            newer = [item for item in batch if cutoff is None or requested_day(item) > cutoff]
            if len(newer) != newer_count:
                verified_count, newer = window(cutoff + timedelta(days=1) if cutoff else date.min, last, newer_count)
                if verified_count != newer_count or len(newer) != newer_count:
                    raise VilpowerUnavailable("VILPOWER returned an incomplete date partition; reload it")
            append_complete(newer)
            count, batch, last = older_count, older, cutoff
        if len(batch) != count:
            raise VilpowerUnavailable("VILPOWER returned incomplete inventory")
        append_complete(batch)
        if len(rows) != total:
            raise VilpowerUnavailable("VILPOWER inventory count changed; reload it")
        return [row for row in rows if not search or search.casefold() in row["template_name"].casefold() or search in row["template_id"]]

    def options(self, template_type, category_id, search, service_type, page=None):
        page = page or self.form()
        categories = page.selects["iCategoryID"]
        services = [{"id": a["value"], "text": page.labels.get(a.get("id", ""), "")} for a in page.inputs if a.get("name") == "iConsentType"]
        if template_type not in {"1", "2", "3"}:
            raise ValueError("Select a valid SMS DLT template type")
        if category_id and category_id not in {option["id"] for option in categories}:
            raise ValueError("Select a category available in the Tata VILPOWER account")
        if service_type and (template_type != "3" or service_type not in {option["id"] for option in services}):
            raise ValueError("Selected service type is not available in the Tata VILPOWER account")
        if template_type == "3" and services and not service_type:
            raise ValueError("Select a service type")
        csrf = page.value("csrfmiddlewaretoken")
        headers = []
        if category_id:
            headers = self.json("/ajaxloadheaders/", {"categoryID": category_id, "template": template_type,
                "htype": "3", "serviceType": service_type, "category": "1", "templatetype": "2", "q": search}, csrf)
        brands = self.json("/ajaxloadbrand/", {"allowClearValue": "true", "q": search}, csrf)
        return {"categories": categories, "headers": _options(headers), "brands": _options(brands), "service_types": services}


def _options(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) or "id" not in row or "text" not in row for row in value):
        raise VilpowerUnavailable("VILPOWER option format changed")
    return [{"id": str(row["id"]), "text": _plain(row["text"])} for row in value if row.get("id") and not row.get("disabled")]


def _normalize(row):
    if not isinstance(row, dict) or not all(key in row for key in ("vcTemplateName", "vcTemplateMessage", "iTemplateIDEn", "iApprovedStatus")):
        raise VilpowerUnavailable("VILPOWER inventory row is incomplete")
    if row.get("Entity") != TATA_ENTITY_NAME:
        raise VilpowerUnavailable("VILPOWER inventory does not belong to Tata Capital")
    if not row["iTemplateIDEn"] or not isinstance(row["vcTemplateName"], str) or not row["vcTemplateName"] or not isinstance(row["vcTemplateMessage"], str):
        raise VilpowerUnavailable("VILPOWER inventory row is incomplete")
    status = {"pending": "pending", "approved": "approved", "disapproved": "rejected", "rejected": "rejected"}.get(_plain(row["iApprovedStatus"]).strip().lower(), "unknown")
    return {"template_name": _content(row["vcTemplateName"]), "template_id": str(row["iTemplateIDEn"]),
        "template_message": _content(row["vcTemplateMessage"]), "status": status,
        "header": _plain(row.get("vcHeader")), "category": _plain(row.get("CATEGORY")),
        "template_type": {"Promotional": "1", "Transactional": "2", "Service": "3"}.get(row.get("ContentTemplateType"), ""),
        "message_type": {"Text": "1", "Regional": "2"}.get(row.get("iTemplateMessageType"), ""),
        "sample_message": _content(row.get("vcSampleMessage")), "entity_id": TATA_ENTITY_ID,
        "brand": _plain(row.get("brand_name")), "requested_at": row.get("RequestedDate", ""),
        "approval_reason": _plain(row.get("DecoratedReason") or row.get("Reason")),
        "template_status": _plain(row.get("STATUS_OTHER")), "provider": "vilpower"}


def validate_session(cookie: str, entity_id: str, client="tata") -> dict[str, str]:
    _scope(client)
    if entity_id != TATA_ENTITY_ID:
        raise ValueError("The supplied principal entity ID must identify Tata Capital")
    values = {"cookie": cookie, "entity_id": entity_id, "provider": "vilpower"}
    portal = _Portal(values)
    try:
        portal.identity()
        return values
    finally:
        portal.close()


def fetch_sms_templates(client="tata", *, credentials=None, search="") -> list[dict]:
    portal = _Portal(_credentials(client, credentials))
    try:
        portal.identity()
        return portal.inventory(search)
    finally:
        portal.close()


def fetch_sms_options(client="tata", template_type="1", category_id="", search="", service_type="", *, credentials=None) -> dict:
    portal = _Portal(_credentials(client, credentials))
    try:
        portal.identity()
        return portal.options(template_type, category_id, search, service_type)
    finally:
        portal.close()

def _sample_matches(body, variables, sample):
    # Memoized bounded fields avoid regex backtracking on adjacent variables.
    literals, offset = [], 0
    for variable in variables:
        literals.append(body[offset:variable.start()])
        offset = variable.end()
    literals.append(body[offset:])

    @cache
    def match(index, position):
        literal = literals[index]
        if not sample.startswith(literal, position):
            return False
        position += len(literal)
        if index == len(variables):
            return position == len(sample)
        kind = variables[index][1]
        limit = 120 if kind in {"urg", "uro"} else 40
        for end in range(position + 1, min(len(sample), position + limit) + 1):
            value = sample[position:end]
            if value.strip() and "{#" not in value and re.fullmatch(_SAMPLE_PATTERNS[kind], value) and match(index + 1, end):
                return True
        return False

    return match(0, 0)



def validate_sms_template(draft: dict) -> list[str]:
    if not isinstance(draft, dict):
        return ["SMS DLT template must be an object"]
    errors = []
    for field in ("template_name", "text", "category_id", "header_id", "header"):
        if not isinstance(draft.get(field), str) or not draft[field].strip():
            errors.append(f"{field} is required")
    for field in ("brand_id", "service_type", "sample_message"):
        if field in draft and not isinstance(draft[field], str):
            errors.append(f"{field} must be text")
    if draft.get("template_type") not in ("1", "2", "3"):
        errors.append("template_type must be 1 (promotional), 2 (transactional), or 3 (service)")
    if draft.get("message_type") not in ("1", "2"):
        errors.append("message_type must be 1 (ASCII) or 2 (regional)")
    name = draft.get("template_name") if isinstance(draft.get("template_name"), str) else ""
    body = draft.get("text") if isinstance(draft.get("text"), str) else ""
    sample = draft.get("sample_message") if isinstance(draft.get("sample_message"), str) else ""
    if len(name) > 60:
        errors.append("Template name cannot exceed the portal's 60-character limit")
    if len(body) > 2000 or len(sample) > 2000:
        errors.append("Template and sample messages cannot exceed the portal's 2000-character limit")
    if draft.get("message_type") == "1" and (not body.isascii() or not sample.isascii()):
        errors.append("ASCII message_type requires ASCII template and sample text")
    variables = list(_VARIABLE.finditer(body))
    remainder = _VARIABLE.sub("", body)
    if "{#" in remainder or "#}" in remainder or re.search(r"\{\{.*?\}\}", body):
        errors.append("Use only exact typed variables {#num#}, {#alp#}, {#urg#}, {#uro#}, {#cbn#}, {#eml#}")
    if len(variables) > 15:
        errors.append("The portal permits at most 15 typed variables")
    if variables and len(variables) <= 15 and len(body) <= 2000 and len(sample) <= 2000:
        if not sample.strip():
            errors.append("sample_message is required when the template contains typed variables")
        elif not _sample_matches(body, variables, sample):
            errors.append("sample_message must preserve the exact template text and replace every typed variable with a valid example")
    elif not variables and sample and sample != body:
        errors.append("Without variables, sample_message must equal the exact template text")
    return errors


def _result(draft, status, *, item=None, error=None, attempted=False, unknown=False):
    return SubmissionResult(source_ref=str(draft.get("source_ref", "")), template_name=str(draft.get("template_name", "")),
        status=status, provider_ref_id=item["template_id"] if item else None,
        provider_response={"provider": "vilpower", "registration_attempted": attempted, "outcome": "unknown" if unknown else ("verified" if item else "failed"),
            "retry_safe": not attempted, **({"template": item} if item else {})}, error=error,
        approval_status=ApprovalStatus(item["status"]) if item else ApprovalStatus.UNKNOWN,
        approval_reason=item.get("approval_reason") if item else None, client="tata", channel="sms",
        submitted_by=str(draft.get("submitted_by") or "Anonymous Operator"), source_file=draft.get("source_file"))


def submit_sms_template(draft: dict, client="tata") -> SubmissionResult:
    _scope(client)
    errors = validate_sms_template(draft)
    if errors:
        return _result(draft if isinstance(draft, dict) else {}, SubmissionStatus.FAILED, error="; ".join(errors))
    portal, attempted = None, False
    try:
        portal = _Portal(_credentials(client, None))
        portal.identity()
        existing = [item for item in portal.inventory(draft["template_name"]) if item["template_name"] == draft["template_name"]]
        if existing:
            exact = next((item for item in existing if item["template_message"] == draft["text"] and item["header"] == draft["header"]), None)
            if exact:
                return _result(draft, SubmissionStatus.DUPLICATE, item=exact)
            return _result(draft, SubmissionStatus.FAILED, error="A different VILPOWER template already uses this exact name")
        page = portal.form()
        options = portal.options(draft["template_type"], draft["category_id"], draft["header"], draft.get("service_type", ""), page)
        if not any(item["id"] == draft["header_id"] and item["text"] == draft["header"] for item in options["headers"]):
            raise ValueError("Header does not match the selected Tata account, template type and category")
        if draft.get("brand_id"):
            brands = portal.options(draft["template_type"], draft["category_id"], "", draft.get("service_type", ""), page)["brands"]
            if draft["brand_id"] not in {item["id"] for item in brands}:
                raise ValueError("Brand is not available in the Tata VILPOWER account")
        form = {"csrfmiddlewaretoken": page.value("csrfmiddlewaretoken"), "reg_catergory": "1",
            "iContentTemplateType": draft["template_type"], "iCategoryID": draft["category_id"],
            "iHeaderID[]": draft["header_id"], "iTemplateMessageType": draft["message_type"],
            "iConsentTemplateID": "", "iLobID": "",
            "vcBrand": draft.get("brand_id", ""), "iContentType": "2", "vcTemplateName": draft["template_name"],
            "vcTemplateMessage": draft["text"], "vcSampleMessage": draft.get("sample_message") or draft["text"]}
        if draft.get("service_type"):
            form["iConsentType"] = draft["service_type"]
        # One registration request, including on timeouts and ambiguous 200/302 responses.
        attempted = True
        post_error = None
        try:
            # Match the browser's multipart form, including empty optional controls.
            response = portal.request("POST", _ADD, data=form,
                files={"vcReason": ("", b"", "application/octet-stream")},
                headers={"Referer": BASE_URL + _ADD, "X-CSRFToken": form["csrfmiddlewaretoken"]})
            if response.status_code == 200:
                form_errors = _HTML(response.text).errors
                if form_errors:
                    return _result(draft, SubmissionStatus.FAILED, error="VILPOWER form rejected the template: " + "; ".join(dict.fromkeys(form_errors)), attempted=True)
        except VilpowerAuthExpired:
            raise
        except VilpowerUnavailable as exc:
            post_error = str(exc)
        try:
            confirmed = [item for item in portal.inventory(draft["template_name"]) if item["template_name"] == draft["template_name"] and item["template_message"] == draft["text"] and item["header"] == draft["header"]]
        except VilpowerUnavailable:
            confirmed = []
        if len(confirmed) == 1:
            return _result(draft, SubmissionStatus.SUBMITTED, item=confirmed[0], attempted=True)
        return _result(draft, SubmissionStatus.FAILED, attempted=True, unknown=True,
            error="Registration outcome unknown. Do not resubmit automatically; reconcile VILPOWER inventory before a new review." + (" " + post_error if post_error else ""))
    except (VilpowerUnavailable, ValueError, OSError) as exc:
        return _result(draft, SubmissionStatus.FAILED, error=str(exc), attempted=attempted, unknown=attempted)
    finally:
        if portal is not None:
            portal.close()
