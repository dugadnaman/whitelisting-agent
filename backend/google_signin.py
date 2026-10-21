"""Google ID-token verification and short-lived, browser-bound login challenges."""

import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException, Request, Response
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWKError, PyJWKSetError

from auth import configured_jwt_secret
from config import _load_env_file

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_JWKS_CLIENT = jwt.PyJWKClient(GOOGLE_JWKS_URL, cache_jwk_set=True, lifespan=300, timeout=5)
CHALLENGE_COOKIE = "karix_google_challenge"
CHALLENGE_AUDIENCE = "karix-google-browser-challenge"
CHALLENGE_SECONDS = 600
COOKIE_PATH = "/api/auth/google"
NO_STORE = {"Cache-Control": "no-store"}
_DOMAIN = re.compile(r"(?=.{1,253}\Z)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\Z")


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    origins: frozenset[str]
    domains: frozenset[str]


def _error(code: int = 401, detail: str = "Google sign-in could not be verified. Please try again.") -> HTTPException:
    return HTTPException(status_code=code, detail=detail, headers=NO_STORE)


def _valid_origin(origin: str) -> bool:
    if not origin or any(char.isspace() for char in origin):
        return False
    try:
        parsed = urlsplit(origin)
        port = parsed.port
        return (
            parsed.scheme in ("https", "http")
            and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and not parsed.path and not parsed.query and not parsed.fragment
            and origin == f"{parsed.scheme}://{parsed.hostname}" + (f":{port}" if port is not None else "")
            and (port is None or 1 <= port <= 65535)
            and (parsed.scheme == "https" or parsed.hostname in ("localhost", "127.0.0.1"))
            and (parsed.hostname == "localhost" or bool(_DOMAIN.fullmatch(parsed.hostname)) or parsed.hostname == "127.0.0.1")
        )
    except ValueError:
        return False


def google_config() -> GoogleConfig | None:
    _load_env_file()
    client_id = os.environ.get("KARIX_GOOGLE_CLIENT_ID", "").strip()
    origins_raw = os.environ.get("KARIX_GOOGLE_ALLOWED_ORIGINS", "").strip()
    domains_raw = os.environ.get("KARIX_GOOGLE_ALLOWED_DOMAINS", "attributics.com").strip()
    if not client_id and not origins_raw:
        return None
    origins = frozenset(value.strip() for value in origins_raw.split(","))
    domains = frozenset(value.strip().lower() for value in domains_raw.split(","))
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", client_id)
        or not origins or not all(_valid_origin(origin) for origin in origins)
        or not domains or not all(_DOMAIN.fullmatch(domain) for domain in domains)
    ):
        raise _error(503, "Google sign-in is unavailable. Use email and password or contact your administrator.")
    return GoogleConfig(client_id, origins, domains)


def _browser_origin(request: Request, config: GoogleConfig) -> str:
    origins = request.headers.getlist("origin")
    if len(origins) != 1 or origins[0] not in config.origins:
        raise _error(403, "Google sign-in is not allowed from this site.")
    return origins[0]


def start_google_signin(request: Request, response: Response) -> dict:
    response.headers.update(NO_STORE)
    config = google_config()
    if config is None:
        return {"enabled": False}
    origin = _browser_origin(request, config)
    nonce = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    challenge = jwt.encode(
        {"aud": CHALLENGE_AUDIENCE, "nonce": nonce, "origin": origin, "client_id": config.client_id,
         "iat": now, "exp": now + timedelta(seconds=CHALLENGE_SECONDS)},
        configured_jwt_secret(), algorithm="HS256",
    )
    response.set_cookie(
        CHALLENGE_COOKIE, challenge, max_age=CHALLENGE_SECONDS, path=COOKIE_PATH,
        httponly=True, secure=origin.startswith("https://") or request.url.scheme == "https", samesite="lax",
    )
    return {"enabled": True, "client_id": config.client_id, "nonce": nonce}


def clear_google_challenge(request: Request, response: Response) -> None:
    response.headers.update(NO_STORE)
    response.delete_cookie(
        CHALLENGE_COOKIE, path=COOKIE_PATH, httponly=True, samesite="lax",
        secure=request.headers.get("origin", "").startswith("https://") or request.url.scheme == "https",
    )


def _challenge_nonce(request: Request, config: GoogleConfig, origin: str) -> str:
    cookie = request.cookies.get(CHALLENGE_COOKIE)
    if not cookie or len(cookie) > 4096:
        raise _error(401, "Google sign-in expired. Please start again.")
    try:
        challenge = jwt.decode(
            cookie, configured_jwt_secret(), algorithms=["HS256"], audience=CHALLENGE_AUDIENCE,
            options={"require": ["aud", "nonce", "origin", "client_id", "iat", "exp"], "strict_aud": True},
        )
        if (
            challenge["origin"] != origin or challenge["client_id"] != config.client_id
            or not isinstance(challenge["nonce"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge["nonce"])
            or type(challenge["iat"]) is not int or type(challenge["exp"]) is not int
            or not 0 < challenge["exp"] - challenge["iat"] <= CHALLENGE_SECONDS
        ):
            raise ValueError("Invalid challenge")
        return challenge["nonce"]
    except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError, RecursionError):
        raise _error(401, "Google sign-in expired. Please start again.") from None


def verify_google_credential(request: Request, credential: str) -> str:
    """Return only an authoritative, verified email; never consume provider authorization claims."""
    config = google_config()
    if config is None:
        raise _error(503, "Google sign-in is unavailable. Use email and password.")
    origin = _browser_origin(request, config)
    nonce = _challenge_nonce(request, config, origin)
    if not isinstance(credential, str) or not 1 <= len(credential) <= 16384:
        raise _error()
    try:
        header = jwt.get_unverified_header(credential)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or not 1 <= len(header["kid"]) <= 256:
            raise ValueError("Invalid signing header")
    except (jwt.InvalidTokenError, TypeError, ValueError, OverflowError, RecursionError):
        raise _error() from None
    try:
        # The token's jku/x5u headers are never used; this client has a fixed Google URL.
        signing_key = GOOGLE_JWKS_CLIENT.get_signing_key(header["kid"])
    except (PyJWKClientConnectionError, PyJWKError, PyJWKSetError, OSError, ValueError, TypeError, KeyError):
        raise _error(503, "Google sign-in is temporarily unavailable. Please try again or use email and password.") from None
    except PyJWKClientError:
        raise _error() from None
    try:
        claims = jwt.decode(
            credential, signing_key.key, algorithms=["RS256"], audience=config.client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={"require": ["iss", "aud", "exp", "iat", "sub", "email", "email_verified", "nonce"]},
        )
        audience = claims["aud"]
        audiences = [audience] if isinstance(audience, str) else audience
        if (
            not isinstance(audiences, list) or not audiences
            or not all(isinstance(value, str) and value for value in audiences)
            or (len(audiences) > 1 and claims.get("azp") != config.client_id)
            or ("azp" in claims and claims["azp"] != config.client_id)
            or type(claims["exp"]) is not int or type(claims["iat"]) is not int
            or claims["exp"] <= claims["iat"]
            or not isinstance(claims["sub"], str) or not 1 <= len(claims["sub"]) <= 255 or claims["sub"].strip() != claims["sub"]
            or claims["email_verified"] is not True
            or not isinstance(claims["nonce"], str) or not secrets.compare_digest(claims["nonce"].encode(), nonce.encode())
            or not isinstance(claims["email"], str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", claims["email"])
        ):
            raise ValueError("Invalid identity claims")
        email = claims["email"].lower()
        domain = email.rsplit("@", 1)[1]
        hosted_domain = claims.get("hd")
        if (
            domain not in config.domains
            or (hosted_domain is not None and (not isinstance(hosted_domain, str) or hosted_domain.lower() != domain))
            or (domain != "gmail.com" and hosted_domain is None)
        ):
            raise ValueError("Email is not authoritative or allowed")
        return email
    except (jwt.PyJWTError, TypeError, ValueError, OverflowError, RecursionError):
        raise _error() from None
