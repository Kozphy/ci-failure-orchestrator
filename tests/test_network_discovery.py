import socket
import ssl
from urllib.error import HTTPError, URLError

from ci_failure_orchestrator.network_discovery import NetworkCapabilityDiscovery


class SocketContext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class TLSContext:
    def __init__(self, error=None):
        self.error = error

    def wrap_socket(self, raw, server_hostname):
        if self.error:
            raise self.error
        return SocketContext()


class Response:
    status = 200


def addresses(*args, **kwargs):
    return [(socket.AF_INET, None, None, None, ("127.0.0.1", 443))]


def test_dns_failure_stops_at_dns_layer():
    probe = NetworkCapabilityDiscovery(resolver=lambda *a, **k: (_ for _ in ()).throw(socket.gaierror()))
    evidence = probe.discover("example.test")
    assert evidence["dns"] == "fail"
    assert evidence["tcp_443"] == "unknown"


def test_ipv4_can_pass_while_ipv6_fails():
    probe = NetworkCapabilityDiscovery(
        resolver=addresses,
        connector=lambda *a, **k: SocketContext(),
        tls_context_factory=lambda: TLSContext(),
        http_opener=lambda *a, **k: Response(),
    )
    evidence = probe.discover("example.test")
    assert evidence | {"ipv4": "pass", "ipv6": "fail"} == evidence
    assert evidence["tls"] == evidence["http"] == "pass"


def test_tls_failure_is_preserved():
    probe = NetworkCapabilityDiscovery(
        resolver=addresses,
        connector=lambda *a, **k: SocketContext(),
        tls_context_factory=lambda: TLSContext(ssl.SSLError("bad cert")),
    )
    assert probe.discover("example.test")["tls"] == "fail"


def test_http_and_authentication_failures_are_distinct():
    common = {
        "resolver": addresses,
        "connector": lambda *a, **k: SocketContext(),
        "tls_context_factory": lambda: TLSContext(),
    }
    failed = NetworkCapabilityDiscovery(**common, http_opener=lambda *a, **k: (_ for _ in ()).throw(URLError("down")))
    assert failed.discover("example.test")["http"] == "fail"
    unauthorized = NetworkCapabilityDiscovery(
        **common,
        http_opener=lambda *a, **k: (_ for _ in ()).throw(HTTPError("https://example.test", 401, "unauthorized", {}, None)),
    )
    evidence = unauthorized.discover("example.test")
    assert evidence["http"] == "pass"
    assert evidence["authentication"] == "fail"
