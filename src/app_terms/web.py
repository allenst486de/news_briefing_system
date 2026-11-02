"""위키백과 문서가 없는 용어의 근거 — 네이버 API HUB 검색(백과사전 → 웹문서).

뜻풀이는 여기서 모은 설명 문장만 근거로 쓴다(pipeline.MEANING_SYSTEM 8번). 근거가 없으면 싣지 않는다.
키는 .env 의 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET (네이버 클라우드 플랫폼 API HUB 발급분).
못 읽으면 빈 결과다 — 위키 없는 용어는 그냥 싣지 않고, 위키 있는 용어 흐름은 영향받지 않는다.
"""
import html
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse

import requests

from ..utils.logger import setup_logger

logger = setup_logger()

HOST = "https://naverapihub.apigw.ntruss.com/search/v1/"
WORKERS = 6                     # 키당 초당 50건 한도 안
SNIPPET_CHARS = 260
_TAG = re.compile(r"<[^>]+>")
_SQUASH = re.compile(r"[^0-9A-Za-z가-힣]+")
_PREFERRED = ("namu.wiki", "terms.naver.com", "ko.wikipedia.org", ".go.kr", ".or.kr")


def _text(value) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", value or ""))).strip()


def _squash(value: str) -> str:
    return _SQUASH.sub("", value or "").lower()


def _search(kind: str, query: str, *, get, display: int) -> List[Dict]:
    headers = {"X-NCP-APIGW-API-KEY-ID": os.environ.get("NAVER_CLIENT_ID", ""),
               "X-NCP-APIGW-API-KEY": os.environ.get("NAVER_CLIENT_SECRET", "")}
    try:
        response = get(HOST + kind, headers=headers, params={"query": query, "display": display}, timeout=10)
        return response.json().get("items", []) if response.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return []


def _evidence_for(candidate: Dict, get) -> Optional[Dict]:
    names = [n for n in (candidate.get("reading"), candidate["head"]) if n]
    keys = [_squash(n) for n in names if len(_squash(n)) >= 2]
    if not keys:
        return None
    for kind, source, display in (("encyc", "네이버 지식백과", 3), ("webkr", "웹", 5)):
        hits = []
        for item in _search(kind, names[0], get=get, display=display):
            title, desc = _text(item.get("title")), _text(item.get("description"))
            # 백과사전은 제목이 용어와 같아야, 웹문서는 제목·설명에 용어가 있어야 근거로 친다
            matched = any(k == _squash(re.sub(r"\(.*?\)", "", title)) for k in keys) if kind == "encyc" \
                else any(k in _squash(title + desc) for k in keys)
            if matched and len(desc) >= 20 and item.get("link"):
                hits.append((desc, item["link"]))
        if hits:
            hits.sort(key=lambda h: not any(p in urlparse(h[1]).netloc for p in _PREFERRED))
            text = " / ".join(d for d, _ in hits[:3])[:SNIPPET_CHARS * (1 if kind == "encyc" else 2)]
            return {"source": source, "url": hits[0][1], "text": text}
    return None


def evidence(candidates: List[Dict], *, get: Callable = requests.get) -> Dict[str, Dict]:
    """{후보 head: {source, url, text}} — 근거를 못 찾은 후보는 키가 없다."""
    if not candidates or not os.environ.get("NAVER_CLIENT_ID") or not os.environ.get("NAVER_CLIENT_SECRET"):
        return {}
    with ThreadPoolExecutor(max_workers=WORKERS) as workers:
        found = list(workers.map(lambda c: _evidence_for(c, get), candidates))
    return {c["head"]: e for c, e in zip(candidates, found) if e}
