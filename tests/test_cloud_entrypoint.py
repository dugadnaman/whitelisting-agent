"""Invalid cloud signing configuration must not start the application services."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker-entrypoint.py"


@pytest.mark.parametrize("secret", [None, "short-signing-key", "a" * 64, " " * 64])
def test_invalid_signing_secret_prevents_service_start(secret, tmp_path):
    environment = os.environ.copy()
    environment.pop("JWT_SECRET", None)
    if secret is not None:
        environment["JWT_SECRET"] = secret
    marker = tmp_path / "application-started"
    result = subprocess.run(
        [
            sys.executable,
            str(ENTRYPOINT),
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
            str(marker),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert not marker.exists()
    if secret and secret.strip():
        assert secret not in result.stderr
