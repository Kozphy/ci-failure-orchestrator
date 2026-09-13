from __future__ import annotations

import socket
import ssl
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class NetworkCapabilityDiscovery:
    """Layered diagnostics only; no proxying or control-bypass behavior."""

    def __init__(
        self,
        *,
        port: int = 443,
        timeout: float = 3.0,
        resolver: Callable[..., list[Any]] = socket.getaddrinfo,
        connector: Callable[..., Any] = socket.create_connection,
        tls_context_factory: Callable[[], ssl.SSLContext] = ssl.create_default_context,
        http_opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.port = port
        self.timeout = timeout
        self.resolver = resolver
        self.connector = connector
        self.tls_context_factory = tls_context_factory
        self.http_opener = http_opener

    def discover(self, host: str | None) -> dict[str, Any]:
        evidence: dict[str, Any] = {
            "host": host,
            "dns": "unknown",
            "ipv4": "unknown",
            "ipv6": "unknown",
            "tcp": "unknown",
            f"tcp_{self.port}": "unknown",
            "tls": "unknown",
            "http": "unknown",
            "authentication": "unknown",
        }
        if not host:
            return evidence
        try:
            addresses = self.resolver(host, self.port, type=socket.SOCK_STREAM)
        except OSError as exc:
            evidence.update(dns="fail", error_type=type(exc).__name__)
            return evidence
        evidence["dns"] = "pass"
        evidence["ipv4"] = "pass" if any(item[0] == socket.AF_INET for item in addresses) else "fail"
        evidence["ipv6"] = "pass" if any(item[0] == socket.AF_INET6 for item in addresses) else "fail"

        try:
            raw_socket = self.connector((host, self.port), timeout=self.timeout)
            evidence["tcp"] = evidence[f"tcp_{self.port}"] = "pass"
        except OSError as exc:
            evidence.update(tcp="fail", error_type=type(exc).__name__)
            evidence[f"tcp_{self.port}"] = "fail"
            return evidence

        try:
            with raw_socket, self.tls_context_factory().wrap_socket(raw_socket, server_hostname=host):
                evidence["tls"] = "pass"
        except (OSError, ssl.SSLError) as exc:
            evidence.update(tls="fail", error_type=type(exc).__name__)
            return evidence

        try:
            response = self.http_opener(Request(f"https://{host}/", method="HEAD"), timeout=self.timeout)
            status = int(getattr(response, "status", 200))
            evidence["http_status"] = status
            evidence["http"] = "pass" if status < 500 else "fail"
            evidence["authentication"] = "fail" if status in {401, 403} else "not_required_or_pass"
        except HTTPError as exc:
            evidence.update(http="pass", http_status=exc.code)
            evidence["authentication"] = "fail" if exc.code in {401, 403} else "not_required_or_pass"
        except URLError as exc:
            evidence.update(http="fail", error_type=type(exc.reason).__name__)
        return evidence
