"""Tests for mcpixmirror.security — network trust and serial pinning."""

from unittest.mock import MagicMock, patch

import pytest

import mcpixmirror.security as security_mod
from mcpixmirror.security import (
    SecurityError,
    assert_trusted_network,
    assert_trusted_serial,
    gateway_mac,
    is_known_serial,
    learn_current_network,
    on_trusted_network,
)


# ------------------------------------------------------------------ #
# gateway_mac                                                          #
# ------------------------------------------------------------------ #


def test_gateway_mac_parses_macos_arp_output():
    route_out = "   route to: default\n    gateway: 192.168.1.254\n  interface: en0\n"
    arp_out = "? (192.168.1.254) at 10:c4:ca:ca:b7:21 on en0 ifscope [ethernet]\n"
    with patch("mcpixmirror.security.subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout=route_out, returncode=0),
            MagicMock(stdout=arp_out, returncode=0),
        ]
        assert gateway_mac() == "10:c4:ca:ca:b7:21"


def test_gateway_mac_returns_empty_when_no_gateway():
    with patch("mcpixmirror.security.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="no route to host\n", returncode=1)
        assert gateway_mac() == ""


def test_gateway_mac_returns_empty_on_timeout():
    import subprocess
    with patch(
        "mcpixmirror.security.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["route"], 5),
    ):
        assert gateway_mac() == ""


# ------------------------------------------------------------------ #
# on_trusted_network                                                   #
# ------------------------------------------------------------------ #


def test_on_trusted_network_true_when_mac_in_allowlist(monkeypatch):
    monkeypatch.setattr(
        security_mod.cfg, "security",
        MagicMock(known_gateway_macs=["aa:bb:cc:dd:ee:ff"], known_ssids=[]),
    )
    with patch("mcpixmirror.security.gateway_mac", return_value="aa:bb:cc:dd:ee:ff"):
        assert on_trusted_network() is True


def test_on_trusted_network_false_when_mac_not_in_allowlist(monkeypatch):
    monkeypatch.setattr(
        security_mod.cfg, "security",
        MagicMock(known_gateway_macs=["aa:bb:cc:dd:ee:ff"], known_ssids=[]),
    )
    with patch("mcpixmirror.security.gateway_mac", return_value="11:22:33:44:55:66"):
        assert on_trusted_network() is False


def test_on_trusted_network_falls_back_to_ssid_when_no_macs(monkeypatch):
    monkeypatch.setattr(
        security_mod.cfg, "security",
        MagicMock(known_gateway_macs=[], known_ssids=["HomeNet"]),
    )
    with patch("mcpixmirror.security._current_ssid", return_value="HomeNet"):
        assert on_trusted_network() is True


def test_on_trusted_network_false_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(
        security_mod.cfg, "security",
        MagicMock(known_gateway_macs=[], known_ssids=[]),
    )
    assert on_trusted_network() is False


def test_assert_trusted_network_raises_when_untrusted(monkeypatch):
    monkeypatch.setattr(
        security_mod.cfg, "security",
        MagicMock(known_gateway_macs=["aa:bb:cc:dd:ee:ff"], known_ssids=[]),
    )
    with patch("mcpixmirror.security.gateway_mac", return_value="11:22:33:44:55:66"):
        with pytest.raises(SecurityError):
            assert_trusted_network()


# ------------------------------------------------------------------ #
# learn_current_network                                               #
# ------------------------------------------------------------------ #


def test_learn_current_network_stores_mac(monkeypatch):
    mock_security = MagicMock()
    mock_security.known_gateway_macs = []
    monkeypatch.setattr(security_mod.cfg, "security", mock_security)
    monkeypatch.setattr(security_mod.cfg, "save", MagicMock())

    with patch("mcpixmirror.security.gateway_mac", return_value="aa:bb:cc:dd:ee:ff"):
        result = learn_current_network()

    assert result == "aa:bb:cc:dd:ee:ff"
    assert "aa:bb:cc:dd:ee:ff" in mock_security.known_gateway_macs


def test_learn_current_network_returns_empty_when_no_gateway(monkeypatch):
    with patch("mcpixmirror.security.gateway_mac", return_value=""):
        assert learn_current_network() == ""


# ------------------------------------------------------------------ #
# Serial pinning                                                       #
# ------------------------------------------------------------------ #


def test_is_known_serial_match(monkeypatch):
    monkeypatch.setattr(
        security_mod.cfg, "security", MagicMock(known_serial="27021FDH200461")
    )
    assert is_known_serial("27021FDH200461") is True


def test_is_known_serial_mismatch(monkeypatch):
    monkeypatch.setattr(
        security_mod.cfg, "security", MagicMock(known_serial="27021FDH200461")
    )
    assert is_known_serial("XXXXXXXXXX") is False


def test_is_known_serial_empty_stored(monkeypatch):
    monkeypatch.setattr(security_mod.cfg, "security", MagicMock(known_serial=""))
    assert is_known_serial("anything") is False


def test_assert_trusted_serial_passes_for_known_serial(monkeypatch):
    monkeypatch.setattr(
        security_mod.cfg, "security", MagicMock(known_serial="SERIAL123")
    )
    assert_trusted_serial("SERIAL123", "Pixel 7")


def test_assert_trusted_serial_raises_for_unknown_serial(monkeypatch):
    monkeypatch.setattr(
        security_mod.cfg, "security", MagicMock(known_serial="SERIAL123")
    )
    with pytest.raises(SecurityError, match="WRONGSERIAL"):
        assert_trusted_serial("WRONGSERIAL", "Pixel 7")


def test_assert_trusted_serial_prompts_on_first_use(monkeypatch):
    monkeypatch.setattr(security_mod.cfg, "security", MagicMock(known_serial=""))
    with patch("mcpixmirror.security.first_use_serial_pin", return_value=True) as mock_pin:
        assert_trusted_serial("NEWSERIAL", "Pixel 7")
        mock_pin.assert_called_once_with("NEWSERIAL", "Pixel 7")


def test_assert_trusted_serial_raises_when_user_declines_first_use(monkeypatch):
    monkeypatch.setattr(security_mod.cfg, "security", MagicMock(known_serial=""))
    with patch("mcpixmirror.security.first_use_serial_pin", return_value=False):
        with pytest.raises(SecurityError, match="not trusted"):
            assert_trusted_serial("NEWSERIAL", "Pixel 7")
