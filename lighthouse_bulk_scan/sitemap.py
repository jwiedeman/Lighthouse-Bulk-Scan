"""Utility functions for locating and parsing sitemaps."""
import requests
import logging
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/91.0.4472.124 Safari/537.36'
    )
}

NON_HTML_EXTENSIONS = (
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.zip', '.rar', '.exe', '.dmg', '.mp3', '.mp4', '.avi', '.mov',
    '.flv', '.wmv', '.mkv', '.ogg', '.ogv', '.webm', '.mpg', '.mpeg'
)

def fetch_sitemaps_from_robots(base_url: str) -> list[str]:
    """
    Fetch the robots.txt file at base_url/robots.txt, parse out 'Sitemap:' lines.
    """
    try:
        robots_url = urljoin(base_url, '/robots.txt')
        logging.info(f"Fetching robots.txt from {robots_url}")
        resp = requests.get(robots_url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        sitemaps = []
        for line in resp.text.splitlines():
            if line.lower().startswith('sitemap:'):
                sitemap_url = line.split(':', 1)[1].strip()
                if not sitemap_url.startswith('http'):
                    sitemap_url = urljoin(base_url, sitemap_url)
                sitemaps.append(sitemap_url)
        return sitemaps
    except requests.RequestException as e:
        logging.warning(f"Failed to fetch robots.txt: {e}")
        return []

def parse_sitemap(url: str) -> list[str]:
    """
    Parse a sitemap or sitemap index. If an index, parse child sitemaps recursively.
    Returns a list of HTML-page URLs (ignoring known asset file extensions).
    """
    urls = []
    logging.info(f"Parsing sitemap: {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        content = r.content

        # Check if it's a sitemap index
        if b"<sitemapindex" in content:
            root = ET.fromstring(content)
            for sitemap in root.findall("{*}sitemap"):
                loc = sitemap.find("{*}loc")
                if loc and loc.text:
                    urls.extend(parse_sitemap(loc.text.strip()))
        else:
            soup = BeautifulSoup(content, "xml")
            url_tags = soup.find_all("url")
            for tag in url_tags:
                loc = tag.find("loc")
                if loc and loc.text:
                    candidate = loc.text.strip()
                    if is_html_page(candidate):
                        urls.append(candidate)
    except Exception as e:
        logging.error(f"Error parsing {url}: {e}")
    return urls

def is_html_page(url: str) -> bool:
    """
    Return True if URL doesn't match known non-HTML file extensions.
    """
    return not any(url.lower().endswith(ext) for ext in NON_HTML_EXTENSIONS)
