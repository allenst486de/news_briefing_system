"""
앱용 시사 용어 저장소 — data/app_terms/YYYY/MM-DD.json (하루 한 파일).

브리핑의 data/terms/YYYY.json 과 섞지 않는다.
  - 내용이 다르다. 여기 뜻풀이는 기사를 보지 않고 쓴 일반적인 뜻이고,
    기사 문장·링크·언론사 이름을 담지 않는다.
  - 쓰는 쪽이 다르다. 이 폴더는 GitHub 서버 작업만 쓰고 맥의 브리핑은 건드리지 않는다.
    같은 파일을 양쪽이 고치면, 맥이 늦게 끝난 날 push 가 충돌해 브리핑 배포까지 막힌다.

중복은 '올해 실린 전체'를 상대로 막는다. 표제·한글 읽기·위키백과 문서 제목 중
하나라도 겹치면 같은 용어로 본다("물가상승"과 "인플레이션"이 같은 문서로 넘어가는 경우).
"""
import json
import os
from datetime import date as Date
from typing import Dict, List, Set

from ..utils.logger import setup_logger
from ..utils.terms_store import normalize_term

logger = setup_logger()

KEEP_RUNS = 20


def day_path(root: str, day: Date) -> str:
    return os.path.join(root, f"{day:%Y}", f"{day:%m-%d}.json")


def empty_day(day: Date) -> Dict:
    return {"date": day.isoformat(), "terms": [], "runs": []}


def load_day(root: str, day: Date) -> Dict:
    path = day_path(root, day)
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict) and isinstance(doc.get("terms"), list):
            doc.setdefault("date", day.isoformat())
            doc.setdefault("runs", [])
            return doc
        logger.warning(f"앱 용어 파일 형식 이상 — 새로 시작: {path}")
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as error:
        # 깨진 파일 하나 때문에 그날 작업이 멈추면 안 된다. 덮어쓰기 전에 옆에 남긴다.
        logger.warning(f"앱 용어 파일을 읽지 못함 ({error}) — {path}.broken 으로 남기고 새로 시작")
        try:
            os.replace(path, path + ".broken")
        except OSError:
            pass
    return empty_day(day)


def save_day(root: str, day: Date, doc: Dict) -> str:
    path = day_path(root, day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc["runs"] = doc.get("runs", [])[-KEEP_RUNS:]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)       # 중간에 죽어도 반쪽 파일이 남지 않게
    return path


def term_keys(entry: Dict) -> Set[str]:
    keys = {normalize_term(entry.get("term")), normalize_term(entry.get("reading"))}
    if entry.get("wikiTitle"):
        keys.add("wiki:" + entry["wikiTitle"])
    keys.discard("")
    return keys


def load_year_terms(root: str, year: int) -> List[Dict]:
    folder = os.path.join(root, str(year))
    if not os.path.isdir(folder):
        return []
    terms = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        for entry in doc.get("terms", []) if isinstance(doc, dict) else []:
            terms.append(entry)
    return terms


def known_keys(root: str, year: int) -> Set[str]:
    keys: Set[str] = set()
    for entry in load_year_terms(root, year):
        keys |= term_keys(entry)
    return keys
