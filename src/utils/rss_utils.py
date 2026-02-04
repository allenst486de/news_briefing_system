import requests
import feedparser
import re
from datetime import datetime


USER_AGENT = {
    "User-Agent": "Mozilla/5.0 (NewsAggregator Bot)"
}


def fetch_feed(url: str):
    try:
        response = requests.get(url, headers=USER_AGENT, timeout=10)
        response.raise_for_status()

        feed = feedparser.parse(response.content)

        if feed.bozo:
            return None

        return feed

    except Exception:
        return None


def clean_html(text: str) -> str:
    return re.sub("<[^<]+?>", "", text or "")


def extract_date(entry, parse_func):
    date_str = entry.get("published") or entry.get("updated") or ""
    return parse_func(date_str)
