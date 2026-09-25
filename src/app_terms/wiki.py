"""
한국어 위키백과 확인 — 앱에 싣는 조건이자 품질 거름망.

한 번에 50개씩 묻고, 용어마다 다음을 본다.
  - 문서가 있는가. 없으면 앱에 싣지 않는다(퍼즐 기획서 4-4). 실측으로도 문서가 없는 말은
    막 생긴 유행어가 대부분이었다(9/14: 15개 중 5개 — 드립덕션, 합의된 현실의 붕괴 등).
  - 넘겨주기를 따라간 최종 문서. '더 읽기' 링크는 최종 문서로 건다.
  - 동음이의 문서인가. 링크가 목록 페이지로 가면 쓸모가 없어 뺀다.
  - 사람 문서인가. 'OOOO년 출생' 같은 분류로 가려낸다. 고르는 단계에서 인명을 빼라고
    해도 섞여 들어오는 경우를 막는다.
  - 나라·지명·작품·기업 문서인가. 고르는 단계에서 빼라고 해도 9/25에 '조선민주주의인민공화국'이
    실렸고, 'Made in Europe'은 딥 퍼플의 라이브 음반 문서로 연결됐다. 위키데이터의 '무엇인가(P31)'로
    먼저 보고, 위키데이터가 없을 때만 한국어 위키백과 분류('유엔 회원국' 등)로 본다.
    국제기구·정부 기관은 시사용어로 쓰므로 거르지 않는다.

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
# 앱 용어로 싣지 않는 문서 — 사람·나라·지명·작품·기업·브랜드·언론·정당.
# 국제기구·정부 기관·위원회(OECD·APEC·BRICS·연방공개시장위원회·특별감찰관 등)는 시사용어로
# 쓰므로 남긴다(2026-09-25 사용자 결정).
#
# 위키데이터 P31(무엇인가) 값으로 먼저 본다.
_ENTITY_TYPES = {
    "Q5",                                                                    # 사람
    "Q6256", "Q3624078", "Q7275",                                            # 나라
    "Q515", "Q1549591", "Q5119", "Q486972", "Q200250", "Q1637706",           # 도시·수도·정착지
    "Q34876", "Q10864048", "Q56061", "Q82794", "Q5107", "Q23442", "Q8502",   # 행정구역·지역·대륙·섬·산
    "Q4022", "Q79007",                                                       # 강·거리
    "Q37901", "Q165", "Q9430", "Q34763", "Q12284", "Q949819", "Q39594",      # 해협·바다·대양·반도·운하·만
    "Q1322134", "Q23397", "Q8072", "Q169358", "Q46831", "Q8514", "Q33837",   # 만·호수·화산·산맥·사막·제도
    "Q46169",                                                                # 국립공원
    "Q4830453", "Q6881511", "Q891723", "Q783794", "Q431289", "Q167270",      # 기업·브랜드·상표
    "Q7278", "Q163740",                                                      # 정당·비영리 단체
    "Q11032", "Q1110794", "Q41298", "Q2085381",                              # 신문·잡지·출판사
    "Q482994", "Q209939", "Q134556", "Q7366", "Q11424", "Q5398426",          # 음반·노래·영화·드라마
    "Q571", "Q7725634", "Q47461344", "Q7889", "Q13406463",                   # 책·작품·게임·목록 문서
    "Q373899",                                                               # 음악 차트(빌보드 핫 100 등)
}
# 위키데이터를 못 읽었거나 문서에 위키데이터가 없을 때만 쓰는 한국어 위키백과 분류.
# (늘 함께 보면 유럽 연합의 'G20 회원국'처럼 남길 문서까지 걸린다)
_ENTITY_CATEGORY = re.compile(
    r"^유엔 회원국$|^(아시아|유럽|아프리카|오세아니아|북아메리카|남아메리카|아메리카)의 (국가|나라)$"
    r"|에 위치한 수도$|의 도시$|의 거리$|설립된 .*기업$|의 정당$"
    r"|음반$|영화$|소설$|싱글$|텔레비전 프로그램$|음악 차트$")
WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def lookup(titles: Iterable[str], *, get=None,
           sleep: Callable[[float], None] = time.sleep) -> Dict[str, Dict]:
    """{물어본 제목: {title, url, disambiguation, person, entity}} — 문서가 없으면 키가 없다."""
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
        "prop": "info|pageprops|categories", "inprop": "url", "ppprop": "disambiguation|wikibase_item",
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

    # 위키데이터 종류 — 못 읽으면 분류로만 판단한다(그 묶음을 버리지는 않는다)
    qids = {title: (page.get("pageprops") or {}).get("wikibase_item") for title, page in pages.items()}
    try:
        types = _wikidata_types([q for q in qids.values() if q], get)
    except Exception as error:
        logger.warning(f"위키데이터 조회 실패 ({type(error).__name__}: {error}) — 분류로만 거른다")
        types = {}

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
            "entity": _is_entity(types.get(qids.get(title)), categories.get(title, ())),
        }
    return result


def _is_entity(kinds, category_names) -> bool:
    """위키데이터 종류가 있으면 그것만 보고, 없을 때만 분류로 판단한다."""
    if kinds:
        return bool(kinds & _ENTITY_TYPES)
    return any(_ENTITY_CATEGORY.search(name) for name in category_names)


def _wikidata_types(qids: List[str], get) -> Dict[str, set]:
    """{Q번호: P31 값 집합}"""
    types: Dict[str, set] = {}
    for start in range(0, len(qids), BATCH):
        chunk = qids[start:start + BATCH]
        resp = get(WIKIDATA_API, params={"action": "wbgetentities", "ids": "|".join(chunk),
                                         "props": "claims", "format": "json"},
                   headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        for qid, entity in (resp.json().get("entities") or {}).items():
            values = set()
            for claim in (entity.get("claims") or {}).get("P31", []):
                value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {}
                if isinstance(value, dict) and value.get("id"):
                    values.add(value["id"])
            types[qid] = values
    return types
