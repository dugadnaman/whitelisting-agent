"""Require a deployment-managed signing secret before starting cloud services."""

import os
import sys

secret = os.environ.get("JWT_SECRET", "").strip()
if (
    len(secret.encode("utf-8")) < 32
    or len(set(secret)) < 16
    or secret == "karix_whitelisting_secure_jwt_secret_key_2026_prod"
):
    sys.exit("JWT_SECRET must be a persistent, strong runtime secret (at least 32 bytes and 16 distinct characters).")

os.execvp(sys.argv[1], sys.argv[1:])
