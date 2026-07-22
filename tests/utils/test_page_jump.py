"""Self-check for page jump parsing."""

from __future__ import annotations

from pagedrop.utils.page_jump import parse_page_jump


def test_single_page():
    assert parse_page_jump("12", 20) == [11]
    assert parse_page_jump(" 3 ", 5) == [2]


def test_range():
    assert parse_page_jump("1-5", 10) == [0, 1, 2, 3, 4]
    assert parse_page_jump("5-1", 10) == [0, 1, 2, 3, 4]
    assert parse_page_jump("1 - 3", 10) == [0, 1, 2]


def test_range_clamps_to_count():
    assert parse_page_jump("3-99", 5) == [2, 3, 4]


def test_invalid():
    assert parse_page_jump("", 5) is None
    assert parse_page_jump("abc", 5) is None
    assert parse_page_jump("0", 5) is None
    assert parse_page_jump("6", 5) is None
    assert parse_page_jump("1-2-3", 5) is None
    assert parse_page_jump("1-", 5) is None
    assert parse_page_jump("-3", 5) is None
    assert parse_page_jump("99-100", 5) is None
