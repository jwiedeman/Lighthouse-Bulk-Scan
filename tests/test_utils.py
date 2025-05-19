import pytest
from lighthouse_bulk_scan.cli import parse_display_value
from lighthouse_bulk_scan.sitemap import is_html_page

@pytest.mark.parametrize("val,expected", [
    ("1.2 s", 1.2),
    ("240 ms", 240.0),
    ("", None),
    (None, None),
])
def test_parse_display_value(val, expected):
    assert parse_display_value(val) == expected

@pytest.mark.parametrize("url,expected", [
    ("https://example.com/index.html", True),
    ("https://example.com/image.png", False),
])
def test_is_html_page(url, expected):
    assert is_html_page(url) == expected
