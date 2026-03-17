"""Tests for mcpixmirror.security — SSID guard and serial pinning."""

from unittest.mock import MagicMock, patch

import pytest

import mcpixmirror.security as security_mod
from mcpixmirror.security import (
    SecurityError,
    assert_trusted_network,
    assert_trusted_serial,
    current_ssid,
    is_known_serial,
    on_trusted_network,
)


# ------------------------------------------------------------------ #
# current_ssid                                                         #
# ------------------------------------------------------------------ #


def test_current_ssid_parses_network_name():
    with patch("mcpixmirror.security.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="Current Wi-Fi Network: HomeNet\n", returncode=0
        )
        assert current_ssid() == "HomeNet"


def test_current_ssid_returns_empty_when_not_associated():
    with patch("mcpixmirror.security.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="You are not associated with an AirPort network.\n", returncode=0
        )
        assert current_ssid() == ""


def test_current_ssid_returns_empty_on_timeout():
    import subprocess

    with patch(
        "mcpixmirror.security.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["networksetup"], 5),
    ):
        assert current_ssid() == ""


def test_current_ssid_returns_empty_when_networksetup_missing():
    with patch(
        "mcpixmirror.security.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        assert current_ssid() == ""


# ------------------------------------------------------------------ #
# on_trusted_network                                                   #
# ------------------------------------------------------------------ #


def test_on_trusted_network_true_when_ssid_in_allowlist(monkeypatch):
    monkeypatch.setattr(security_mod.cfg, "security", MagicMock(known_ssids=["HomeNet"]))
    with patch("mcpixmirror.security.current_ssid", return_value="HomeNet"):
        assert on_trusted_network() is True


def test_on_trusted_network_false_when_ssid_not_in_allowlist(monkeypatch):
    monkeypatch.setattr(security_mod.cfg, "security", MagicMock(known_ssids=["HomeNet"]))
    with patch("mcpixmirror.security.current_ssid", return_value="CoffeeShopWiFi"):
        assert on_trusted_network() is False


def test_on_trusted_network_false_when_no_ssids_configured(monkeypatch):
    monkeypatch.setattr(security_mod.cfg, "security", MagicMock(known_ssids=[]))
    assert on_trusted_network() is False


def test_assert_trusted_network_raises_on_untrusted(monkeypatch):
    monkeypatch.setattr(security_mod.cfg, "security", MagicMock(known_ssids=["HomeNet"]))
    with patch("mcpixmirror.security.current_ssid", return_value="Evil"):
        with pytest.raises(SecurityError, match="Evil"):
            assert_trusted_network()


def test_assert_trusted_network_raises_when_not_connected(monkeypatch):
    monkeypatch.setattr(security_mod.cfg, "security", MagicMock(known_ssids=["HomeNet"]))
    with patch("mcpixmirror.security.current_ssid", return_value=""):
        with pytest.raises(SecurityError, match="Not connected"):
            assert_trusted_network()


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
    # Should not raise
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
