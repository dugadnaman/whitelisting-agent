#!/usr/bin/python3
"""Fail closed before LinuxServer /init; expose DevTools on private NICs only."""
import ipaddress
import json
import os
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

CHROME_CLI = "--remote-debugging-address=127.0.0.1 --remote-debugging-port=9223 --disable-dev-shm-usage about:blank"
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
))
PLACEHOLDERS = ("changeme", "change-me", "change_me", "password", "placeholder", "example", "replace", "default")


def validate_config(env):
    user = env.get("CUSTOM_USER", "")
    password = env.get("PASSWORD", "")
    if (len(user) < 8 or len(set(user)) < 4 or not user.isascii()
            or any(not (char.isalnum() or char in "._-@") for char in user)
            or user.lower() in {"administrator", "chromium", "apparel", "username"}
            or any(word in user.lower() for word in PLACEHOLDERS)):
        raise ValueError("CUSTOM_USER must be a non-default ASCII login of at least 8 characters using letters, digits, . _ - @")
    if (len(password) < 32 or len(set(password)) < 12 or password != password.strip()
            or not password.isascii() or any(ord(char) < 32 or ord(char) == 127 for char in password)
            or any(word in password.lower() for word in PLACEHOLDERS)):
        raise ValueError("PASSWORD must be a strong, non-placeholder secret of at least 32 characters; use a randomly generated value")
    mode = env.get("APPAREL_BROWSER_STREAM_ACCESS", "")
    if mode not in {"trusted-network", "authenticated-proxy"}:
        raise ValueError("APPAREL_BROWSER_STREAM_ACCESS must explicitly select trusted-network or authenticated-proxy")
    if mode == "authenticated-proxy":
        url = urlsplit(env.get("APPAREL_BROWSER_PUBLIC_URL", ""))
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment):
            raise ValueError("APPAREL_BROWSER_PUBLIC_URL must be the HTTPS URL of the authenticated reverse proxy")
        if env.get("APPAREL_BROWSER_PROXY_AUTH") not in {"oidc", "oauth2-proxy", "authentik", "authelia", "mtls"}:
            raise ValueError("APPAREL_BROWSER_PROXY_AUTH must declare robust proxy authentication, not HTTP basic auth")
    # A direct Railway domain bypasses the separately deployed authentication proxy.
    if env.get("RAILWAY_PUBLIC_DOMAIN") or env.get("RAILWAY_TCP_PROXY_DOMAIN"):
        raise ValueError("Remove browser public domains/TCP proxies; expose only the authenticated reverse proxy")
    if env.get("CHROME_CLI", CHROME_CLI) != CHROME_CLI:
        raise ValueError("CHROME_CLI must use the fixed loopback DevTools configuration on port 9223")


def private_addresses(interfaces, requested=""):
    addresses = set()
    for interface in interfaces:
        for info in interface.get("addr_info", []):
            address = ipaddress.ip_address(info["local"])
            if any(address.version == network.version and address in network for network in PRIVATE_NETWORKS):
                addresses.add(str(address))
    if requested:
        # An explicit address must be BOTH private and actually assigned to this container.
        if requested not in addresses:
            raise ValueError("CDP_BIND_ADDRESS must be an assigned RFC1918 IPv4 or unique-local IPv6 address")
        addresses = {requested}
    if not addresses:
        raise ValueError("No private interface for CDP; attach the browser to a private deployment network")
    return sorted(addresses)


def forward_cdp():
    interfaces = json.loads(subprocess.check_output(["ip", "-j", "address", "show"], text=True))
    addresses = private_addresses(interfaces, os.environ.get("CDP_BIND_ADDRESS", ""))
    children = []

    def stop(signum, frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for address in addresses:
            ipv6 = ipaddress.ip_address(address).version == 6
            listener = (f"TCP6-LISTEN:9222,bind=[{address}],ipv6only=1,reuseaddr,fork" if ipv6
                        else f"TCP4-LISTEN:9222,bind={address},reuseaddr,fork")
            children.append(subprocess.Popen(["socat", listener, "TCP:127.0.0.1:9223"], start_new_session=True))
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError("A private CDP listener exited")
    finally:
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


def main():
    try:
        validate_config(os.environ)
        if sys.argv[1:] == ["--cdp-forward"]:
            forward_cdp()
        else:
            # Keep command overrides from bypassing validation or starting a second service.
            if sys.argv[1:]:
                raise ValueError("Browser command overrides are not supported; use the image entrypoint")
            os.environ["CHROME_CLI"] = CHROME_CLI
            os.execv("/init", ["/init"])
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        # Validation errors never include usernames/passwords or full environment values.
        print(f"Browser startup refused: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
