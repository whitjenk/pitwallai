"""Subscribe flow legal copy and DELETE handler."""

from __future__ import annotations

import pytest

from whatsapp import subscribe_flow as sub_mod


def test_subscribe_confirm_under_320_chars() -> None:
    assert len(sub_mod._SUBSCRIBE_CONFIRM) <= 320
    assert "Independent fan tool" in sub_mod._SUBSCRIBE_CONFIRM
    assert "F1 Fantasy" in sub_mod._SUBSCRIBE_CONFIRM


def test_subscribe_data_note_under_160_chars() -> None:
    assert len(sub_mod._SUBSCRIBE_DATA_NOTE) <= 160
    assert "DELETE" in sub_mod._SUBSCRIBE_DATA_NOTE
