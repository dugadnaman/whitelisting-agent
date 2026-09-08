"""
Cryptographic utilities for Karix SMS API integration.

Implements:
1. AES-256 CBC with PBKDF2WithHmacSHA1 for Personally Identifiable Information (PII)
   encryption on destination mobile numbers and message content (per Karix Send SMS API specification).
2. AES-GCM encryption and decryption for SMS Delivery Report (DLR) HTTPs Callback Webhooks
   (per Karix DLR Forwarding Integration Guide).
"""
import base64
import os

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ---------------------------------------------------------------------------
# PII Encryption / Decryption (AES-256-CBC + PBKDF2WithHmacSHA1, 11 iterations)
# ---------------------------------------------------------------------------

def _derive_aes_key(password_str: str, salt: bytes) -> bytes:
    """Derive 256-bit AES key using PBKDF2 with HMAC-SHA1 and 11 iterations."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=32,  # 256 bits
        salt=salt,
        iterations=11,
    )
    return kdf.derive(password_str.encode("utf-8"))


def encrypt_sms_pii(text: str, secure_key_b64: str) -> str:
    """
    Encrypt a text string (mobile number or message content) using AES-256 CBC.

    Matches Karix Send SMS API specification:
    - Base64-decoded secure_key provides the password string.
    - 20 random salt bytes generated via OS CSPRNG.
    - Key derived via PBKDF2WithHmacSHA1 (11 iterations, 256 bits).
    - 16 random IV bytes generated.
    - Encrypted via AES-256-CBC with PKCS5/PKCS7 padding.
    - Output buffer: saltBytes (20) + ivBytes (16) + encryptedTextBytes.
    - Returns Base64-encoded string.
    """
    if not text:
        return ""

    # Decode base64 password
    try:
        password_str = base64.b64decode(secure_key_b64).decode("utf-8")
    except Exception:
        password_str = secure_key_b64

    salt_bytes = os.urandom(20)
    iv_bytes = os.urandom(16)
    key = _derive_aes_key(password_str, salt_bytes)

    # Apply PKCS7 padding
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(text.encode("utf-8")) + padder.finalize()

    # Encrypt AES-256-CBC
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv_bytes))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()

    # Combine: salt (20) + iv (16) + ciphertext
    buffer = salt_bytes + iv_bytes + ciphertext
    return base64.b64encode(buffer).decode("utf-8")


def decrypt_sms_pii(encrypted_b64: str, secure_key_b64: str) -> str:
    """
    Decrypt an encrypted PII string (mobile number or message content).

    Matches Karix Send SMS API specification:
    - Decode Base64 buffer.
    - Extract salt (first 20 bytes), IV (next 16 bytes), ciphertext (remaining bytes).
    - Derive AES-256 key from decoded password and salt.
    - Decrypt AES-256-CBC and remove PKCS5/PKCS7 padding.
    - Returns original plain text string.
    """
    if not encrypted_b64:
        return ""

    try:
        raw = base64.b64decode(encrypted_b64.strip())
    except Exception as e:
        raise ValueError(f"Invalid base64 payload: {e}") from e

    if len(raw) < 36:
        raise ValueError("Encrypted buffer too short (must contain at least 20-byte salt + 16-byte IV)")

    salt_bytes = raw[:20]
    iv_bytes = raw[20:36]
    ciphertext = raw[36:]

    # Decode base64 password
    try:
        password_str = base64.b64decode(secure_key_b64).decode("utf-8")
    except Exception:
        password_str = secure_key_b64

    key = _derive_aes_key(password_str, salt_bytes)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv_bytes))
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    data = unpadder.update(padded_data) + unpadder.finalize()
    return data.decode("utf-8")


# ---------------------------------------------------------------------------
# DLR AES-GCM Encryption / Decryption
# ---------------------------------------------------------------------------

def _normalize_key_bytes(key: str | bytes) -> bytes:
    """Normalize key string or bytes to standard AES key length (16, 24, or 32 bytes)."""
    if isinstance(key, str):
        key_bytes = key.encode("utf-8")
    else:
        key_bytes = key

    if len(key_bytes) in (16, 24, 32):
        return key_bytes
    if len(key_bytes) < 16:
        return key_bytes.ljust(16, b"\0")
    if len(key_bytes) < 24:
        return key_bytes[:16]
    if len(key_bytes) < 32:
        return key_bytes[:24]
    return key_bytes[:32]


def _normalize_iv_bytes(iv: str | bytes) -> bytes:
    """Normalize IV string or bytes for GCM (standard 12 or 16 bytes)."""
    if isinstance(iv, str):
        iv_bytes = iv.encode("utf-8")
    else:
        iv_bytes = iv

    if len(iv_bytes) in (12, 16):
        return iv_bytes
    if len(iv_bytes) < 12:
        return iv_bytes.ljust(12, b"\0")
    return iv_bytes[:12]


def encrypt_dlr_gcm(
    data: str,
    key: str | bytes,
    init_vector: str | bytes,
    tag_length: int = 16,
) -> str:
    """
    Encrypt JSON DLR payload string using AES in GCM mode.

    Per Karix DLR integration guide:
    - SecretKeySpec: key.getBytes("UTF-8"), "AES"
    - GCMParameterSpec: tag_length * 8, init_vector.getBytes()
    - Cipher: AES/GCM/NoPadding
    - Result: Base64 encoded string containing ciphertext + 16-byte authentication tag.
    """
    key_bytes = _normalize_key_bytes(key)
    iv_bytes = _normalize_iv_bytes(init_vector)

    aesgcm = AESGCM(key_bytes)
    ciphertext_with_tag = aesgcm.encrypt(iv_bytes, data.encode("utf-8"), None)
    return base64.b64encode(ciphertext_with_tag).decode("utf-8")


def decrypt_dlr_gcm(
    encrypted_b64: str,
    key: str | bytes,
    init_vector: str | bytes,
    tag_length: int = 16,
) -> str:
    """
    Decrypt an AES-GCM encrypted DLR payload from Karix.

    - Base64 decodes the encrypted payload.
    - Decrypts and verifies the 16-byte GCM authentication tag.
    - Returns plain JSON string.
    """
    raw_cipher = base64.b64decode(encrypted_b64.strip())
    key_bytes = _normalize_key_bytes(key)
    iv_bytes = _normalize_iv_bytes(init_vector)

    aesgcm = AESGCM(key_bytes)
    decrypted_bytes = aesgcm.decrypt(iv_bytes, raw_cipher, None)
    return decrypted_bytes.decode("utf-8")
