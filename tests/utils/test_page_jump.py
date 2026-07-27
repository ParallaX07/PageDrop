"""Self-check for page jump parsing."""

from __future__ import annotations

from pagedrop.utils.page_jump import (
    format_indices_as_ranges,
    parse_page_jump,
    parse_page_ranges,
)


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


def test_parse_page_ranges_multi():
    assert parse_page_ranges("1-3,5,7-9", 10) == [(0, 2), (4, 4), (6, 8)]
    assert parse_page_ranges(" 2 , 4-5 ", 5) == [(1, 1), (3, 4)]
    assert parse_page_ranges("", 5) is None
    assert parse_page_ranges("1-3,", 5) is None


def test_format_indices_as_ranges():
    assert format_indices_as_ranges([0, 1, 2, 4, 7, 8]) == "1-3,5,8-9"
    assert format_indices_as_ranges([]) == ""
    assert format_indices_as_ranges([3]) == "4"
