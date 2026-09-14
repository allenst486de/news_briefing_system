"""
한국어 위키백과 확인 — 앱에 싣는 조건이자 품질 거름망.

한 번에 50개씩 묻고, 용어마다 다음을 본다.
  - 문서가 있는가. 없으면 앱에 싣지 않는다(퍼즐 기획서 4-4). 실측으로도 문서가 없는 말은
    막 생긴 유행어가 대부분이었다(9/14: 15개 중 5개 — 드립덕션, 합의된 현실의 붕괴 등).
  - 넘겨주기를 따라간 최종 문서. '더 읽기' 링크는 최종 문서로 건다.
  - 동음이의 문서인가. 링크가 목록 페이지로 가면 쓸모가 없어 뺀다.
  - 사람 문서인가. 'OOOO년 출생' 같은 분류로 가려낸다. 고르는 단계에서 인명을 빼라고
    해도 섞여 들어오는 경우를 막는다.

글은 가져오지 않는다. 문서가 있는지와 제목·주소만 본다 — 뜻풀이는 따로 쓴다.
실패하면 그 묶음은 빈 결과다. 확인하지 못한 용어는 싣지 않고 다음 회차에 다시 본다.
"""
import re
import time
import urllib.parse
from typing import Callable, Dict, Iterable, List

import requests

from ..utils.logger import setup_logger

logger = setup_logger()

WIKI_API = "https://ko.wikipedia.org/w/api.php"
USER_AGENT = ("NewsBriefingSystem/1.0 "
              "(app terms; https://github.com/allenst486de/news_briefing_system)")
BATCH = 50
_MAX_CONTINUE = 5
_PERSON_CATEGORY = re.compile(r"^\d+년 (출생|사망)$|^살아있는 사람$|^생년 미상$|^몰년 미상$")


def lookup(titles: Iterable[str], *, get=None,
           sleep: Callable[[float], None] = time.sleep) -> Dict[str, Dict]:
    """{물어본 제목: {title, url, disambiguation, person}} — 문서가 없으면 키가 없다."""
    get = get or requests.get
    wanted = [t for t in dict.fromkeys((t or "").strip() for t in titles) if t]
    found: Dict[str, Dict] = {}
    for start in range(0, len(wanted), BATCH):
        chunk = wanted[start:start + BATCH]
        if start:
            sleep(1.0)      # 연달아 치면 호출 제한에 걸린다
        try:
            found.update(_lookup_chunk(chunk, get))
        except Exception as error:
            logger.warning(f"위키백과 조회 실패 ({type(error).__name__}: {error}) — 이 묶음은 다음 회차에")
    return found


def _lookup_chunk(chunk: List[str], get) -> Dict[str, Dict]:
    params = {
        "action": "query", "format": "json", "formatversion": "2", "redirects": "1",
        "prop": "info|pageprops|categories", "inprop": "url", "ppprop": "disambiguation",
        "clshow": "!hidden", "cllimit": "max", "titles": "|".join(chunk),
    }
    pages: Dict[str, Dict] = {}
    categories: Dict[str, set] = {}
    normalized: Dict[str, str] = {}
    redirects: Dict[str, str] = {}

    extra: Dict[str, str] = {}
    for _ in range(_MAX_CONTINUE):
        resp = get(WIKI_API, params={**params, **extra},
                   headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        query = data.get("query", {})
        for item in query.get("normalized", []):
            normalized[item["from"]] = item["to"]
        for item in query.get("redirects", []):
            redirects[item["from"]] = item["to"]
        for page in query.get("pages", []):
            title = page.get("title", "")
            # 분류가 많으면 같은 문서가 continue 응답에 다시 온다 — 정보는 합친다
            merged = pages.setdefault(title, {})
            merged.update({k: v for k, v in page.items() if k != "categories"})
            names = categories.setdefault(title, set())
            for category in page.get("categories", []):
                names.add(category.get("title", "").split(":", 1)[-1])
        if "continue" not in data:
            break
        extra = {k: str(v) for k, v in data["continue"].items()}

    result = {}
    for asked in chunk:
        title = normalized.get(asked, asked)
        title = redirects.get(title, title)
        page = pages.get(title)
        if not page or page.get("missing") or page.get("invalid"):
            continue
        url = page.get("fullurl") or ("https://ko.wikipedia.org/wiki/"
                                      + urllib.parse.quote(title.replace(" ", "_")))
        result[asked] = {
            "title": page.get("title", title),
            "url": urllib.parse.unquote(url),
            "disambiguation": "disambiguation" in (page.get("pageprops") or {}),
            "person": any(_PERSON_CATEGORY.match(name) for name in categories.get(title, ())),
        }
    return result
