"""Network transport helpers for mail servers behind macOS Fake-IP proxies."""
from __future__ import annotations

import ipaddress
import json
import os
import platform
import socket
import subprocess
import time
import urllib.parse
import urllib.request


_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_IP_BOUND_IF = 25  # Darwin's IP_BOUND_IF socket option.
_DNS_CACHE: dict[str, tuple[float, list[str]]] = {}


def host_uses_fake_ip(host: str) -> bool:
    try:
        addresses = {row[4][0].split("%", 1)[0] for row in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    for raw in addresses:
        try:
            if ipaddress.ip_address(raw) in _FAKE_IP_NETWORK:
                return True
        except ValueError:
            continue
    return False


def _resolve_public_ipv4(host: str) -> list[str]:
    cached = _DNS_CACHE.get(host)
    now = time.time()
    if cached and cached[0] > now:
        return list(cached[1])
    query = urllib.parse.urlencode({"name": host, "type": "A"})
    request = urllib.request.Request(
        f"https://dns.google/resolve?{query}",
        headers={"Accept": "application/dns-json", "User-Agent": "Captain/0.2"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.load(response)
    addresses: list[str] = []
    for answer in payload.get("Answer", []):
        if answer.get("type") != 1:
            continue
        raw = str(answer.get("data") or "")
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if ip.version == 4 and ip.is_global and ip not in _FAKE_IP_NETWORK:
            addresses.append(str(ip))
    addresses = list(dict.fromkeys(addresses))
    if not addresses:
        raise OSError(f"public DNS returned no usable address for {host}")
    _DNS_CACHE[host] = (now + 600, addresses)
    return addresses


def _physical_interfaces() -> list[str]:
    configured = os.environ.get("CAPTAIN_MAIL_DIRECT_INTERFACE", "").strip()
    if configured:
        return [configured]
    interfaces: list[str] = []
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["networksetup", "-listallhardwareports"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            blocks = result.stdout.split("\n\n")
            for block in blocks:
                if "Hardware Port: Wi-Fi" not in block and "Hardware Port: Ethernet" not in block:
                    continue
                for line in block.splitlines():
                    if line.startswith("Device: "):
                        interfaces.append(line.split(":", 1)[1].strip())
        except (OSError, subprocess.SubprocessError):
            pass
    interfaces.extend(["en0", "en1"])
    return list(dict.fromkeys(name for name in interfaces if name))


def _direct_macos_connection(host: str, port: int, timeout: float | None) -> socket.socket:
    errors: list[str] = []
    for address in _resolve_public_ipv4(host):
        for interface in _physical_interfaces():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            try:
                index = socket.if_nametoindex(interface)
                sock.setsockopt(socket.IPPROTO_IP, _IP_BOUND_IF, index)
                sock.connect((address, port))
                return sock
            except OSError as exc:
                errors.append(f"{interface}/{address}: {exc}")
                sock.close()
    detail = "; ".join(errors[-4:]) or "no physical network interface is available"
    raise OSError(f"direct mail connection to {host}:{port} failed: {detail}")


def create_mail_connection(host: str, port: int, timeout: float | None) -> socket.socket:
    """Create a TCP connection, bypassing a macOS Fake-IP tunnel when needed."""
    if platform.system() == "Darwin" and host_uses_fake_ip(host):
        return _direct_macos_connection(host, port, timeout)
    return socket.create_connection((host, port), timeout)
