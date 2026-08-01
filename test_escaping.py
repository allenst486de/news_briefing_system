"""
Self-check: XSS 회귀 방지 검증
- HTMLGenerator가 autoescape로 렌더링하는지 (html_generator.py)
- NewsArticle이 javascript: 등 위험한 링크 스킴을 차단하는지 (base_collector.py)

python test_escaping.py 로 실행. 실패 시 AssertionError로 즉시 중단.
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.collectors.base_collector import NewsArticle
from src.html_generator import HTMLGenerator


def test_link_scheme_blocked():
    evil = NewsArticle(
        title="normal title",
        link="javascript:alert(1)",
        published=datetime.now(),
    )
    assert evil.link == "", f"위험한 link 스킴이 차단되지 않음: {evil.link!r}"

    safe = NewsArticle(
        title="normal title",
        link="https://example.com/a",
        published=datetime.now(),
    )
    assert safe.link == "https://example.com/a"


def test_html_output_is_escaped():
    template_dir = os.path.join(os.path.dirname(__file__), "src", "templates")
    output_dir = tempfile.mkdtemp(prefix="test_escaping_")
    try:
        article = NewsArticle(
            title='<img src=x onerror=alert(1)>',
            link="https://example.com/a",
            published=datetime.now(),
            summary="A & B",
            source="test",
        )
        article.original_title = '<script>alert(2)</script>'
        article.original_summary = "C & D"

        gen = HTMLGenerator(template_dir, output_dir)
        out_file = os.path.join(output_dir, "out.html")
        gen._generate_briefing_page(
            category="domestic_general",
            articles=[article],
            output_file=out_file,
            date_str="2026-01-01",
            date_path="2026/01/01",
        )

        with open(out_file, "r", encoding="utf-8") as f:
            html = f.read()

        assert "<img src=x onerror" not in html, "제목의 <img> 태그가 이스케이프되지 않음 (XSS)"
        assert "&lt;img" in html, "제목이 이스케이프된 형태로 출력되지 않음"
        assert "<script>alert(2)</script>" not in html, "원문 제목의 <script>가 이스케이프되지 않음 (XSS)"
        assert "A &amp; B" in html, "요약의 & 가 이스케이프되지 않음"
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    test_link_scheme_blocked()
    test_html_output_is_escaped()
    print("OK: escaping regression checks passed")
