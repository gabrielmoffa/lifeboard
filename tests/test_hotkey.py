import pytest
from lifeboard.hotkey import parse_hotkey

CMD, SHIFT, OPT, CTRL = 1 << 8, 1 << 9, 1 << 11, 1 << 12


def test_basic_combo():
    assert parse_hotkey("cmd+shift+l") == (CMD | SHIFT, 37)


def test_just_key():
    assert parse_hotkey("l") == (0, 37)


def test_case_insensitive():
    assert parse_hotkey("CMD+SHIFT+L") == parse_hotkey("cmd+shift+l")


def test_order_insensitive():
    assert parse_hotkey("shift+cmd+l") == parse_hotkey("cmd+shift+l")


def test_opt_alias_for_alt():
    assert parse_hotkey("opt+return") == parse_hotkey("alt+return")


def test_command_alias_for_cmd():
    assert parse_hotkey("command+l") == parse_hotkey("cmd+l")


def test_function_key():
    assert parse_hotkey("ctrl+alt+f5") == (CTRL | OPT, 96)


def test_space():
    assert parse_hotkey("cmd+space") == (CMD, 49)


def test_arrow():
    assert parse_hotkey("cmd+left") == (CMD, 123)


def test_esc_alias():
    assert parse_hotkey("esc") == parse_hotkey("escape")


@pytest.mark.parametrize("bad", ["", "   ", "+", "++"])
def test_empty_raises(bad):
    with pytest.raises(ValueError):
        parse_hotkey(bad)


def test_only_modifier_raises():
    with pytest.raises(ValueError):
        parse_hotkey("cmd")


def test_two_keys_raises():
    with pytest.raises(ValueError):
        parse_hotkey("cmd+a+b")


def test_unknown_modifier_raises():
    with pytest.raises(ValueError):
        parse_hotkey("meta+a")


def test_unknown_key_raises():
    with pytest.raises(ValueError):
        parse_hotkey("cmd+foo")
