from __future__ import annotations

import socket
import threading

import pytest

from celestron_aux import AuxTimeout, discover


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_discover_returns_the_address_of_whatever_announces_itself() -> None:
    port = _free_udp_port()

    def announce() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(b'{"AMW007"}', ("127.0.0.1", port))

    timer = threading.Timer(0.2, announce)
    timer.start()
    try:
        assert discover(timeout=5, port=port) == "127.0.0.1"
    finally:
        timer.join()


def test_discover_raises_when_nothing_announces_itself() -> None:
    with pytest.raises(AuxTimeout):
        discover(timeout=0.2, port=_free_udp_port())
