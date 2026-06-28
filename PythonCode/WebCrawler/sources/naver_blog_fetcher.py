from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
import re

import requests
from bs4 import BeautifulSoup

from .naver_blog import canonicalize_blog_url


BLOG_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)


def normalize_blog_url(url: str) -> str:
    canonical_url = canonicalize_blog_url(url)
    parsed = urlsplit(canonical_url)
    hostname = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]

    if hostname == "blog.naver.com" and len(path_parts) >= 2:
        return f"https://m.blog.naver.com/{path_parts[0]}/{path_parts[1]}"

    return canonical_url


def fetch_blog_post(url: str, timeout: int = 10) -> dict[str, Any]:
    request_url = normalize_blog_url(url)
    response = requests.get(
        request_url,
        headers={
            "User-Agent": BLOG_USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        },
        timeout=timeout,
    )

    return {
        "request_url": url,
        "normalized_url": request_url,
        "final_url": response.url,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type"),
        "html": response.text,
    }


def extract_blog_text(html: str, *, url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    remove_noise_nodes(soup)

    iframe = soup.select_one("iframe#mainFrame[src]")
    if iframe:
        # Desktop blog shell. The caller should normally use the mobile URL,
        # but keep this hint in metadata by returning None rather than shell text.
        return None

    for selector in (
        ".se-main-container",
        "#postViewArea",
        ".post_ct",
        ".post-view",
        ".se_component_wrap",
        "article",
    ):
        node = soup.select_one(selector)
        text = clean_extracted_text(node.get_text("\n", strip=True)) if node else ""
        if is_meaningful_blog_text(text):
            return text

    fallback = clean_extracted_text(soup.get_text("\n", strip=True))
    if is_meaningful_blog_text(fallback):
        return fallback

    return None


def remove_noise_nodes(soup: BeautifulSoup) -> None:
    for node in soup.select(
        "script, style, noscript, iframe, nav, header, footer, .u_likeit, "
        ".section_t1, .blog2_container, .post_btn, .wrap_postcomment"
    ):
        node.decompose()


def clean_extracted_text(text: str) -> str:
    lines = []
    seen_blank = False
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            if not seen_blank:
                lines.append("")
            seen_blank = True
            continue

        seen_blank = False
        lines.append(line)

    return "\n".join(lines).strip()


def is_meaningful_blog_text(text: str | None) -> bool:
    if not text:
        return False
    if len(text) < 120:
        return False

    lowered = text.lower()
    noise_terms = ("로그인", "공감", "댓글", "블로그", "이웃추가")
    return not all(term in lowered for term in noise_terms)
