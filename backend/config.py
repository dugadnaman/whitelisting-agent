"""
Configuration for the Karix WhatsApp template submission pipeline.

Portal sessions and one-time settings are loaded from encrypted scoped storage,
with account-specific deployment environment defaults.
Never hardcode new credentials in source files.

Auth model:
    Portal requests require Authorization, Session and User from one login.
    Auth Sync captures these after a human completes mobile OTP.
    Official API requests use WABA_AUTH_TOKEN with the Authentication header;
    submission/listing currently prefer an available portal session.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth credentials — read fresh from env on every call so that a token
# refresh (e.g. via a wrapper script that re-exports env vars) is picked
# up without restarting the process.
# ---------------------------------------------------------------------------


_PREEXISTING_ENV = frozenset(os.environ.keys())


def _load_env_file():
    """Load key-value pairs from credentials.json and .env file if present.

    Precedence: real environment variables (e.g. Render dashboard env vars)
    always win over file values — files are defaults only. This prevents the
    git-tracked credentials.json from overriding tokens set in the dashboard,
    which survive deploys unlike Render's ephemeral filesystem.
    """

    import json
    from pathlib import Path

    # 1. Load credentials.json (saved from Settings UI)
    cred_json_path = Path("credentials.json")
    if cred_json_path.exists():
        try:
            creds = json.loads(cred_json_path.read_text(encoding="utf-8"))
            for k, v in creds.items():
                if k and v and k not in os.environ:
                    os.environ[k] = str(v).strip()
        except Exception:
            pass

    # 2. Load .env file
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and v and k not in os.environ:
                os.environ[k] = v


def _account_prefix(client: str) -> str:
    """Sanitize client name into uppercase environment variable prefix."""
    import re

    return re.sub(r"[^a-zA-Z0-9_]", "_", client).strip("_").upper()


def get_portal_auth_headers(
    client: str = "bajaj",
    *,
    bearer_token: str | None = None,
    session_id: str | None = None,
    portal_user: str | None = None,
) -> dict[str, str]:
    """
    Build HTTP headers for portal requests, optionally using an unsaved Settings snapshot.
    Overrides stay request-local; saved credentials remain strictly isolated per account.
    """
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)
    if c == "bajaj":
        bearer = os.environ.get("BAJAJ_KARIX_BEARER_TOKEN") or os.environ.get("KARIX_BEARER_TOKEN")
        session = os.environ.get("BAJAJ_KARIX_SESSION") or os.environ.get("KARIX_SESSION")
        user = os.environ.get("BAJAJ_KARIX_USER") or os.environ.get("KARIX_USER")
    else:
        # Strict tenant separation: each sub-account has its own portal login
        # (e.g. TCHFL=TATACAPWABA, TCL_PROMO=TATACAPPROMO). Never inherit the
        # parent TATA_* session — submitting under another login's session is
        # what caused Meta's "invalid media handle" cross-WABA rejections.
        bearer = os.environ.get(f"{prefix}_KARIX_BEARER_TOKEN")
        session = os.environ.get(f"{prefix}_KARIX_SESSION")
        user = os.environ.get(f"{prefix}_KARIX_USER") or os.environ.get(f"{prefix}_PORTAL_USER")
    from portal_sessions import load_session, load_settings
    settings = load_settings(c, "whatsapp")
    bearer = settings.get(f"{prefix}_KARIX_BEARER_TOKEN", bearer)
    session = settings.get(f"{prefix}_KARIX_SESSION", session)
    user = settings.get(f"{prefix}_KARIX_USER", user)
    if bearer_token is None or session_id is None or portal_user is None:
        saved_session = load_session(c, "whatsapp")
        if saved_session:
            bearer = saved_session["bearer_token"]
            session = saved_session["session"]
            user = saved_session["user"]
    if bearer_token is not None:
        bearer = bearer_token
    if session_id is not None:
        session = session_id
    if portal_user is not None:
        user = portal_user
    bearer = re.sub(r"^(?:Authorization\s*:\s*)?Bearer(?:\s+|$)", "", (bearer or "").strip(), flags=re.IGNORECASE).strip()
    session = (session or "").strip()
    user = (user or "").strip()

    # Mobile OTP login remains human-operated. Karix Auth Sync captures the
    # resulting session and stores it encrypted in the database.

    missing = []
    if not bearer:
        missing.append(f"{prefix}_KARIX_BEARER_TOKEN" if c != "bajaj" else "BAJAJ_KARIX_BEARER_TOKEN")
    if not session:
        missing.append(f"{prefix}_KARIX_SESSION" if c != "bajaj" else "BAJAJ_KARIX_SESSION")
    if not user:
        missing.append(f"{prefix}_KARIX_USER" if c != "bajaj" else "BAJAJ_KARIX_USER")
    if missing:
        raise OSError(
            f"Missing required Karix portal credentials for {client}: {', '.join(missing)}. "
            f"Open Settings → {client} → Connect extension, log in with your mobile OTP, "
            "and open the WhatsApp template list; or use the explicit manual override."
        )

    return {
        "Authorization": f"Bearer {bearer}",
        "Session": session,
        "User": user,
        "Origin": KARIX_ORIGIN,
        "Referer": KARIX_REFERER,
    }


def get_official_auth_headers(client: str = "bajaj") -> dict[str, str]:
    """
    Build headers for the official WhatsApp Template API for the given client.
    Strictly isolated per account. Never cross-contaminates another WABA account.
    """
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)

    if c == "bajaj":
        token = (
            os.environ.get("BAJAJ_WABA_AUTH_TOKEN")
            or os.environ.get("WABA_AUTH_TOKEN")
            or DEFAULT_WABA_AUTH_TOKENS.get("bajaj")
        )
    else:
        token = os.environ.get(f"{prefix}_WABA_AUTH_TOKEN") or DEFAULT_WABA_AUTH_TOKENS.get(c)
    from portal_sessions import load_settings
    token = load_settings(c, "whatsapp").get(f"{prefix}_WABA_AUTH_TOKEN", token)
    if not token:
        expected_key = f"{prefix}_WABA_AUTH_TOKEN" if c != "bajaj" else "BAJAJ_WABA_AUTH_TOKEN"
        raise OSError(
            f"Missing required WABA API Token for {client} ({expected_key}). "
            f"Please enter the API Token in Settings under {client} before submitting."
        )
    return {"Authentication": f"Bearer {token}"}


def get_waba_id(client: str = "bajaj") -> str:
    """
    Return WABA ID for the given client.
    Strictly isolated per account. Never uses another account's WABA ID.
    """
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)

    from portal_sessions import load_settings
    saved = load_settings(c, "whatsapp")
    waba = saved.get(f"{prefix}_WABA_ID") or os.environ.get(f"{prefix}_WABA_ID")
    if c == "bajaj":
        waba = waba or os.environ.get("WABA_ID")
    waba = waba or DEFAULT_WABA_IDS.get(c)
    if not waba:
        raise OSError(f"Missing WABA ID for {client} ({prefix}_WABA_ID). Configure this account in Settings.")
    return waba


def _esmeaddr_from_session_token(token: str | None) -> str | None:
    """
    Decode the esmeaddr embedded in a Karix portal session token.

    Token payload format: <random><esmeaddr><ACCOUNT_NAME>, e.g.
      'msijafen72148300000000BFDL_WABA'      -> 72148300000000 (Bajaj)
      'msx42ip072516600000000TATACAPPROMO'   -> 72516600000000
      'mt89yco272389800000000TATACAPWABA'    -> 72389800000000 (TCHFL)

    Decode only for conflict rejection; configured identity plus provider
    verification remain authoritative. An unsigned payload never establishes identity.
    """
    if not token or "." not in token:
        return None
    try:
        import base64

        payload = base64.urlsafe_b64decode(token.split(".")[1] + "==").decode("utf-8", errors="replace")
        m = re.search(r"(\d{14,15})([A-Z_]+)$", payload)
        if not m:
            return None
        digits = m.group(1)
        return digits[1:] if len(digits) == 15 else digits
    except Exception:
        return None


def get_esmeaddr(client: str = "bajaj") -> str:
    """
    Return ESME address for the given client.

    Resolve the server-owned expected identity from encrypted account settings,
    then exact deployment environment and account defaults; never adopt a token's identity.
    """
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)
    from portal_sessions import load_settings
    saved = load_settings(c, "whatsapp")
    esme = saved.get(f"{prefix}_ESMEADDR") or os.environ.get(f"{prefix}_ESMEADDR")
    if c == "bajaj":
        esme = esme or os.environ.get("ESMEADDR")
    esme = esme or DEFAULT_ESMEADDRS.get(c)
    if not esme:
        raise OSError(f"Missing ESMEADDR for {client} ({prefix}_ESMEADDR). Configure this account in Settings.")
    return esme


def get_template_namespace_id(client: str = "bajaj") -> str:
    """Return template namespace ID for the given client."""
    _load_env_file()
    c = (client or "bajaj").lower().strip()
    prefix = _account_prefix(c)
    from portal_sessions import load_settings
    saved = load_settings(c, "whatsapp").get(f"{prefix}_TEMPLATE_NAMESPACE_ID")
    if saved:
        return saved
    if c == "bajaj":
        return (
            os.environ.get("BAJAJ_TEMPLATE_NAMESPACE_ID")
            or os.environ.get("TEMPLATE_NAMESPACE_ID")
            or BAJAJ_TEMPLATE_NAMESPACE_ID
        )
    return (
        os.environ.get(f"{prefix}_TEMPLATE_NAMESPACE_ID")
        or os.environ.get("TATA_TEMPLATE_NAMESPACE_ID")
        or GLOBAL_TEMPLATE_NAMESPACE_ID
    )


# ---------------------------------------------------------------------------
# Fixed constants — same for every request on this Bajaj WABA account.
# ---------------------------------------------------------------------------

KARIX_BASE_URL = "https://rcsgui.karix.solutions/v1.0/templates"
OFFICIAL_TEMPLATE_BASE_URL = "https://rcsgui.karix.solutions/api/v1.0/template"

KARIX_ORIGIN = "https://rcmui.instaalerts.zone"
KARIX_REFERER = "https://rcmui.instaalerts.zone/"

BAJAJ_WABA_ID = "286109054585247"
BAJAJ_ESMEADDR = "72148300000000"
BAJAJ_TEMPLATE_NAMESPACE_ID = "42eec6e7_6287_4b1d_8ec8_52f4a80c23b5"
# ---------------------------------------------------------------------------
# Account-level permanent constants
# ---------------------------------------------------------------------------
GLOBAL_TEMPLATE_NAMESPACE_ID = "42eec6e7_6287_4b1d_8ec8_52f4a80c23b5"

DEFAULT_WABA_IDS: dict[str, str] = {
    "bajaj": "286109054585247",
    "tcl_promo": "1064104141771475",
    "tcl_trans": "1139151984921982",
    "tchfl": "734197179371393",
    "moneyfy": "575085772325234",
}

DEFAULT_ESMEADDRS: dict[str, str] = {
    "bajaj": "72148300000000",
    "tcl_promo": "72516600000000",
    "tcl_trans": "72519700000000",
    "tchfl": "72389800000000",
    "wealth": "72516600000000",
    "moneyfy": "72516600000000",
    "apparel": "71189600000000",
}

DEFAULT_ENTITY_IDS: dict[str, str] = {
    "bajaj": "110100001654",
    "tata": "1001490234791338781",
    "tcl_promo": "1001490234791338781",
    "tcl_trans": "1001490234791338781",
    "tchfl": "1001490234791338781",
    "wealth": "1001490234791338781",
    "moneyfy": "1001490234791338781",
}
DEFAULT_WABA_AUTH_TOKENS: dict[str, str] = {
    "bajaj": "eyJhbGciOiJSUzI1NiJ9.bXNpamFmZW43MjE0ODMwMDAwMDAwMEJGRExfV0FCQQ.FnFUC20YGZCWKrn26J5K3_l3vHQCtLVrAeIJTsObGorYwRiEortZ4Dc2D25jv9A6cLT9I0DYqzimMKGenw24pUncHR53xLS6xBsjXfuehuidjbvoqjqcmF0A4Vw-oCqY3fPMcvOv59yI9H8A7wEUdYuRrlNKu7cAQNjGAl_Kf6In6XeRq3hWXVxS3ESCRBvch23DqexfwT5lY8DBg5Aox3AtrxZvk4tpLrRYRoOSubjlL7vruF8zKc_WT4CVAbh0CcwqN4fXeHG6eNdofbY7-J-E2nNVvFgki3HUsAjq9xtnLyEk2ONccrfWtEGqvUyASynJz_YP52DnXzqvIRa1wA",
    "tcl_promo": "FJc9VaV5lCu9wErhDQS1pg==",
    "tcl_trans": "kBouGcp2L9b0pr0nkCLRVg==",
    "tchfl": "QFRmWCMXpuflaXFuJ0l2jQ==",
    "moneyfy": "ljR9Pi3XaisbCvyZEue8lA==",
}

DEFAULT_PORTAL_BEARER_TOKENS: dict[str, str] = {
    "bajaj": "eyJhbGciOiJSUzI1NiJ9.bXNpamFmZW43MjE0ODMwMDAwMDAwMEJGRExfV0FCQQ.FnFUC20YGZCWKrn26J5K3_l3vHQCtLVrAeIJTsObGorYwRiEortZ4Dc2D25jv9A6cLT9I0DYqzimMKGenw24pUncHR53xLS6xBsjXfuehuidjbvoqjqcmF0A4Vw-oCqY3fPMcvOv59yI9H8A7wEUdYuRrlNKu7cAQNjGAl_Kf6In6XeRq3hWXVxS3ESCRBvch23DqexfwT5lY8DBg5Aox3AtrxZvk4tpLrRYRoOSubjlL7vruF8zKc_WT4CVAbh0CcwqN4fXeHG6eNdofbY7-J-E2nNVvFgki3HUsAjq9xtnLyEk2ONccrfWtEGqvUyASynJz_YP52DnXzqvIRa1wA",
    "tcl_promo": "eyJhbGciOiJSUzI1NiJ9.bXVjYzN3ZHI3MjUxNjYwMDAwMDAwMFRBVEFDQVBQUk9NTw.bijSeGe5uh0iRG_fm2BDcn3oATp-kGhUdBxPMt2Oc_Nc82g0mlkOxsq8LJgs9E4iuL0HkABEHCvqqmpSgsHI9fVTOGMMymXMGyvG6lgr3gTmxun-hwJixz1kp-B6oQuW0zt8iiQ57pe1IleFmYoGx8r5QmwL7WdL6D3DLCiQxWBSHJpL7Wv9iApQBSI1Awtj3RAtoqvj3sLuJpE2sfa_dcmxCXvStIx5y7KFRABMB1IdDENxh4taocVy1DT_PsNS-m4cCPI0l_8JDkT9miT53k0kpDbWJHSPecgdMclKoLYvNBVAxtTtRrKvtSAO_1UZOFQ0m9sNwkNMmueoIRE5LQ",
    "tcl_trans": "eyJhbGciOiJSUzI1NiJ9.bXU1ODNvZWo3MjUxOTcwMDAwMDAwMFRBVEFDQVBUUkFOUw.CA4QdRkM4xKJ4U7tNP6um0l2Ir8TuC13WAHcqaUruI8Aeuy1HxTfyP_qDC0-Z_-fAJkW3J_QlI57VW21coDOr-PPx4ApDEex-Uifphvs6eic7PFSH8ILoSzXa70jrINPw8iZlgjUVjQTY5ZF0xlGvxe1VhF2fYEqXxjDym7rwKlNYrJ9WQ58sBlse3QeDdDZDYQLDKo9rrkMVsOKZgLPCSIqS-jBK2UNmHnTx7Kxall8ggELv1Vxu9vTh2xmFZdH_hck8WLwSOQLZGJnzlrgRhPplM59injRcIK95UkeYicUYPS5xaJSIuhKr_V6zLmrU2Xwq8bs0SAYPFUIvXKavQ",
    "tchfl": "eyJhbGciOiJSUzI1NiJ9.bXQ4OXljbzI3MjM4OTgwMDAwMDAwMFRBVEFDQVBXQUJB.fY0YcL-l7GGZkTtv4zyzI7yQFfhV9aTG72bnHEEmN2L2DTfXRqeq2OucP0035ROBRDg2Oid-Z6DCRs2aOmlDQefurK7mMIbjqXxQFQS6M69PhqpLzs-KapgvyMWQDKmfx_rk1lmS0AX2RLqvv3Iws3QN8Vxx-dgEvO9uqySqsxFtPCcanWHAM8922BVw6CL3BEyiuV874Z1WkWXkSzHCjWwQCoNL4FncPypX7ePnb1OFOXUALH5Wacz1OUq228ATYq56M3oDlhwAZjFoWpjIw53hMjwHR3Vw3QkHKDue-KAxqWLOxtNtioN7Ahhx578eWf8iSlWETOkJIaVQ5VSZ7A",
    "moneyfy": "eyJhbGciOiJSUzI1NiJ9.bXR2M3Jua2U3MjUxOTgwMDAwMDAwMFRBVEFTRUNfTVVTS0FO.b2Xxj9XqGuAEOD3PilflUZKnQr5Bm0wD6G1hCF2rUGpGxknIDfzGmRw90wEnlsv1YiKteTsdq7B7DB2_nZZuimoD8O4QdFo0LYrOaTxigxJmCbxizEDBJDpAwFFi66SJlaVLItvusSemJKot0dzaRqTMXqyXtumel9I_PodKxh_Rkt1TKyvrUHdPraKX-Uj79vCmwKfn9u8ZSjsqGfO4IRTg8VDurj3a7a3LlzifJIf8KOqX-bdBRqSoEkvHlxBka-bGeSVm_QF-RTw9IK6Y4zADORabNyY7SE19qzJOxcgb3xteFBueZ8cJl9sfJEArK2iW7bz2XDSS-jY1f2GhHA",
    "apparel": "eyJhbGciOiJSUzI1NiJ9.bXVlMjR3OHc3MTE4OTYwMDAwMDAwMG1ham9yZG5k.cOsG-iaMMhZBDb23dZ3lioQBgI3F4Qy4nk83KL_m_ZQgrJGD7ibHbF9hwF2ts7RwjpDLmNxapE6ZHfeB1C0EYNjZYJIZPp5XDsTRjcc8PkD5eBdNJhEUjcIFN_6BS1_XhuMDgmzXz8oL79GFi_RIMOMU9IdVp6lNJBCnr2m-MwZiMl7Ew0_9OxpTHyuCCAaH6w9o0nd1ud11SOk9wVWvgTfXa7ZOumSQCx_4STJFvXAa4Yn_-KIHWWnYReZU2ApyTPTFC8ebuGbLws5-cYJDqbcBESYK1MScTzftE0OLhSIiRiJXPQuP5Eb1vuOwWo8bFxTuWgdpRiHiuv3gOfgynQ",
}

DEFAULT_PORTAL_SESSIONS: dict[str, str] = {
    "bajaj": "6a757401c8ba692973064983",
    "tcl_promo": "6ab229d3aad057009b292969",
    "tcl_trans": "6aab9a2baad057009b15b57d",
    "tchfl": "6a8d33dac8ba692973555b95",
    "moneyfy": "6aa243c6aad057009bf8ccbf",
    "apparel": "6ab3c0caaad057009b30dc8e",
}

DEFAULT_PORTAL_USERS: dict[str, str] = {
    "bajaj": "Nirmal",
    "tcl_promo": "Parth",
    "tcl_trans": "Parth",
    "tchfl": "Muskan",
    "wealth": "TATASEC_MUSKAN",
    "moneyfy": "Parth",
    "apparel": "Vijay",
}
