"""Subscribe flow legal copy and DELETE handler."""

from __future__ import annotations

import pytest

from whatsapp import commands as cmd_mod


def test_subscribe_confirm_under_320_chars() -> None:
    assert len(cmd_mod._SUBSCRIBE_CONFIRM) <= 320
    assert "Independent fan tool" in cmd_mod._SUBSCRIBE_CONFIRM
    assert "F1 Fantasy" in cmd_mod._SUBSCRIBE_CONFIRM


def test_subscribe_data_note_under_160_chars() -> None:
    assert len(cmd_mod._SUBSCRIBE_DATA_NOTE) <= 160
    assert "DELETE" in cmd_mod._SUBSCRIBE_DATA_NOTE
