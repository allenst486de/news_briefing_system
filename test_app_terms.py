"""
Self-check: 앱용 시사 용어 작업(src/app_terms) 검증.

NVIDIA·위키백과·RSS 에 실제로 나가지 않는다. 호출 함수를 전부 가짜로 바꿔 끼워
"응답이 멈췄다", "429 가 왔다", "모델이 기사에 없는 말을 골랐다" 같은 상황을 재현한다.
API 키도 네트워크도 필요 없다.

python test_app_terms.py 로 실행. 실패 시 AssertionError로 즉시 중단.
"""
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests  # noqa: E402

from src.app_terms import nim, pipeline, store, wiki  # noqa: E402

DAY = date(2026, 9, 14)


# ── 가짜 부품 ─────────────────────────────────────────────────────────────

class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeResponse:
    def __init__(self, status=200, lines=(), headers=None, fail_after=None, on_line=None):
        self.status_code = status
        self.headers = headers or {}
        self._lines = list(lines)
        self._fail_after = fail_after
        self._on_line = on_line
        self.closed = False

    def iter_lines(self):
        for index, line in enumerate(self._lines):
            if self._fail_after is not None and index >= self._fail_after:
                # requests 는 스트리밍 중 read timeout 을 ConnectionError 로 감싸 올린다
                raise requests.exceptions.ConnectionError("Read timed out.")
            if self._on_line:
                self._on_line()
            yield line

    def close(self):
        self.closed = True


def sse(*pieces):
    lines = [("data: " + json.dumps({"choices": [{"delta": {"content": p}}]},
                                    ensure_ascii=False)).encode("utf-8") for p in pieces]
    return lines + [b"", b"data: [DONE]"]


class FakePost:
    def __init__(self, responses):
        self.responses = list(responses)
        self.keys = []

    def __call__(self, url, headers=None, json=None, stream=None, timeout=None):
        assert stream is True and json["stream"] is True, "스트리밍으로 불러야 한다"
        self.keys.append(headers["Authorization"].split()[-1])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeWiki:
    """물어본 제목마다 문서가 있다고 답한다. 예외 목록으로 없음·동음이의·사람을 흉내 낸다."""

    def __init__(self, missing=(), person=(), disambiguation=(), redirect=None):
        self.missing, self.person, self.disambiguation = set(missing), set(person), set(disambiguation)
        self.redirect = redirect or {}
        self.asked = []

    def __call__(self, titles):
        titles = list(titles)
        self.asked.extend(titles)
        found = {}
        for title in titles:
            if title in self.missing:
                continue
            final = self.redirect.get(title, title)
            found[title] = {"title": final, "url": f"https://ko.wikipedia.org/wiki/{final}",
                            "disambiguation": title in self.disambiguation,
                            "person": title in self.person}
        return found


class FakeChat:
    """시스템 프롬프트로 고르기/뜻풀이를 구분한다."""

    def __init__(self, discoveries=(), fail_meanings=(), down=False, concepts=None):
        self.discoveries = list(discoveries)
        self.fail_meanings = set(fail_meanings)
        self.concepts = concepts or {}
        self.down = down
        self.calls = []

    def __call__(self, pool, system_prompt, user_prompt, **kwargs):
        kind = "discovery" if system_prompt == pipeline.DISCOVERY_SYSTEM else "meaning"
        self.calls.append((kind, user_prompt))
        if self.down:
            return None
        if kind == "discovery":
            return json.dumps(self.discoveries.pop(0) if self.discoveries else [], ensure_ascii=False)
        assert "기사 목록" not in user_prompt and " — " not in user_prompt, "뜻풀이 호출에 기사 글이 섞이면 안 된다"
        items = []
        for number, label in re.findall(r"^(\d+)\. (.+?) · 기사 분야", user_prompt, flags=re.M):
            meaning = "" if label in self.fail_meanings else \
                f"{label}은 시험용으로 만든 일반적인 뜻풀이 문장으로, 길이 조건을 채우려고 조금 길게 적는다."
            item = {"n": int(number), "meaning": meaning}
            if label in self.concepts:
                item["category"] = self.concepts[label]
            items.append(item)
        return json.dumps(items, ensure_ascii=False)


def make_repo(root, news_terms=(), raw=None):
    os.makedirs(os.path.join(root, "data", "terms"), exist_ok=True)
    with open(os.path.join(root, "data", "terms", "2026.json"), "w", encoding="utf-8") as f:
        json.dump([{"term": t, "category": c, "date": DAY.isoformat(), "definition": "기사 기반 풀이",
                    "link": "https://news.example/1", "source": "어느신문"} for t, c in news_terms],
                  f, ensure_ascii=False)
    if raw is not None:
        path = pipeline.raw_path(root, DAY)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"date": DAY.isoformat(), "categories": raw}, f, ensure_ascii=False)


def one_key_pool():
    return nim.KeyPool([("NVIDIA_API_KEY", "k")])


# ── nim: 키 돌리기 ────────────────────────────────────────────────────────

def test_key_pool_dedupes_and_rotates():
    pool = nim.KeyPool.from_env({"NVIDIA_API_KEY": "a", "NVIDIA_API_KEY_IT": "a",
                                 "NVIDIA_API_KEY_WORLD": "b", "NVIDIA_API_KEY_TERMS": " "})
    assert [label for label, _ in pool.alive()] == ["NVIDIA_API_KEY", "NVIDIA_API_KEY_WORLD"]
    picks = [pool.acquire()[0][1] for _ in range(3)]
    assert picks == ["a", "b", "a"], picks


def test_key_pool_cool_and_drop():
    clock = FakeClock()
    pool = nim.KeyPool([("A", "a"), ("B", "b")], clock)
    pool.cool("A", 30)
    pool.cool("B", 10)
    picked, wait = pool.acquire()
    assert picked is None and wait == 10
    clock.now += 10
    assert pool.acquire()[0][0] == "B"
    pool.drop("A")
    pool.drop("B")
    assert len(pool) == 0 and pool.acquire() == (None, 0.0)


# ── nim: 호출 ─────────────────────────────────────────────────────────────

def test_chat_joins_stream_pieces():
    nim.reset_stats()
    post = FakePost([FakeResponse(lines=sse("안녕", "하세요"))])
    assert nim.chat(one_key_pool(), "s", "u", post=post) == "안녕하세요"
    assert nim.STATS["ok"] == 1


def test_chat_429_moves_to_another_key():
    nim.reset_stats()
    clock = FakeClock()
    pool = nim.KeyPool([("A", "a"), ("B", "b")], clock)
    post = FakePost([FakeResponse(status=429, headers={"Retry-After": "30"}),
                     FakeResponse(lines=sse("ok"))])
    assert nim.chat(pool, "s", "u", post=post, clock=clock, sleep=clock.sleep) == "ok"
    assert post.keys == ["a", "b"] and nim.STATS["rate_limited"] == 1
    assert pool.acquire()[0][0] == "B", "429 난 키는 Retry-After 동안 쉬어야 한다"


def test_chat_stalled_stream_retries_on_other_key():
    nim.reset_stats()
    post = FakePost([FakeResponse(lines=sse("반쪽", "응답"), fail_after=1),
                     FakeResponse(lines=sse("완성"))])
    pool = nim.KeyPool([("A", "a"), ("B", "b")])
    assert nim.chat(pool, "s", "u", post=post, sleep=lambda s: None) == "완성"
    assert nim.STATS["stalled"] == 1 and post.keys == ["a", "b"]


def test_chat_slow_drip_hits_call_timeout():
    nim.reset_stats()
    clock = FakeClock()

    def tick():
        clock.now += 100    # 조각은 오지만 한 조각에 100초 — idle 에는 안 걸리고 늘어지는 경우

    post = FakePost([FakeResponse(lines=sse("가", "나", "다"), on_line=tick),
                     FakeResponse(lines=sse("빠른 응답"))])
    pool = nim.KeyPool([("A", "a"), ("B", "b")], clock)
    assert nim.chat(pool, "s", "u", post=post, clock=clock, sleep=clock.sleep) == "빠른 응답"
    assert nim.STATS["stalled"] == 1


def test_chat_connect_error_then_success():
    nim.reset_stats()
    post = FakePost([requests.exceptions.ConnectTimeout("connect timed out"),
                     FakeResponse(lines=sse("ok"))])
    assert nim.chat(nim.KeyPool([("A", "a"), ("B", "b")]), "s", "u", post=post) == "ok"


def test_chat_drops_rejected_keys_and_stops_on_bad_request():
    nim.reset_stats()
    post = FakePost([FakeResponse(status=401), FakeResponse(status=403)])
    assert nim.chat(nim.KeyPool([("A", "a"), ("B", "b")]), "s", "u", post=post) is None
    assert nim.STATS["dropped_keys"] == 2 and not post.responses

    post = FakePost([FakeResponse(status=404), FakeResponse(lines=sse("안 불려야 함"))])
    assert nim.chat(nim.KeyPool([("A", "a"), ("B", "b")]), "s", "u", post=post) is None
    assert len(post.responses) == 1, "404 는 다른 키로 바꿔도 같으므로 재시도하지 않는다"


def test_chat_respects_deadline():
    clock = FakeClock()
    post = FakePost([])
    assert nim.chat(one_key_pool(), "s", "u", deadline=clock() - 1, post=post, clock=clock) is None
    assert post.keys == []


def test_chat_gives_up_after_max_attempts():
    nim.reset_stats()
    post = FakePost([FakeResponse(status=500) for _ in range(nim.MAX_ATTEMPTS)])
    clock = FakeClock()
    pool = nim.KeyPool([("A", "a")], clock)
    assert nim.chat(pool, "s", "u", post=post, clock=clock, sleep=clock.sleep) is None
    assert nim.STATS["calls"] == nim.MAX_ATTEMPTS


# ── wiki ──────────────────────────────────────────────────────────────────

def test_wiki_lookup_follows_redirects_and_flags_pages():
    responses = [
        {"continue": {"clcontinue": "123|x", "continue": "||"},
         "query": {
             "redirects": [{"from": "IPO", "to": "기업공개"}],
             "pages": [
                 {"title": "기업공개", "fullurl": "https://ko.wikipedia.org/wiki/%EA%B8%B0%EC%97%85%EA%B3%B5%EA%B0%9C",
                  "categories": [{"title": "분류:증권"}]},
                 {"title": "머큐리", "fullurl": "https://ko.wikipedia.org/wiki/머큐리",
                  "pageprops": {"disambiguation": ""}},
                 {"title": "홍길동", "fullurl": "https://ko.wikipedia.org/wiki/홍길동",
                  "categories": [{"title": "분류:경제인"}]},
                 {"title": "없는말", "missing": True},
             ]}},
        {"query": {"pages": [{"title": "홍길동", "categories": [{"title": "분류:1970년 출생"}]}]}},
    ]
    asked = []

    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    def get(url, params=None, headers=None, timeout=None):
        asked.append(params)
        return Resp(responses.pop(0))

    found = wiki.lookup(["IPO", "머큐리", "홍길동", "없는말"], get=get, sleep=lambda s: None)
    assert found["IPO"]["title"] == "기업공개"
    assert found["IPO"]["url"] == "https://ko.wikipedia.org/wiki/기업공개"
    assert found["머큐리"]["disambiguation"] and not found["IPO"]["disambiguation"]
    assert found["홍길동"]["person"], "continue 응답에 온 출생 분류도 합쳐 봐야 한다"
    assert "없는말" not in found
    assert asked[1]["clcontinue"] == "123|x"


def test_wiki_lookup_survives_errors():
    def get(*args, **kwargs):
        raise requests.exceptions.ConnectionError("down")
    assert wiki.lookup(["인플레이션"], get=get, sleep=lambda s: None) == {}


# ── 글자 규칙 ─────────────────────────────────────────────────────────────

def test_split_and_appears_in():
    assert pipeline.split_term("인플레이션(Inflation)") == ("Inflation", "인플레이션")
    assert pipeline.split_term("사자성어(四字成語)") == ("사자성어", "")
    assert pipeline.split_term("USMCA") == ("USMCA", "")
    assert pipeline.appears_in("킬 스위치(kill switch)", "정부, 킬스위치 도입 검토")
    assert pipeline.appears_in("스태그플레이션(stagflation)", "Fears of stagflation grow")
    assert not pipeline.appears_in("양적완화", "한은, 기준금리 동결")


def test_tidy_headword():
    assert pipeline.tidy_headword("kill switch") == "Kill Switch"
    assert pipeline.tidy_headword("IPO") == "IPO"
    assert pipeline.tidy_headword("Connectome") == "Connectome"
    assert pipeline.tidy_headword("인사청문회") == "인사청문회"


def test_valid_meaning_rejects_news_context():
    ok = "물가가 전반적으로 오르고 돈의 가치가 떨어지는 현상을 말한다. 수요가 늘거나 생산 비용이 오를 때 나타난다."
    assert pipeline.valid_meaning(ok) == ok
    assert pipeline.valid_meaning("짧은 풀이") is None
    assert pipeline.valid_meaning(ok + " 최근 미국 선거의 쟁점이 됐다.") is None
    assert pipeline.valid_meaning("2026년 도입된 제도로, 공공기관이 일정 조건을 갖춘 기업에 세금을 깎아 주는 것을 말한다.") is None
    assert pipeline.valid_meaning("오늘날 널리 쓰이는 결제 방식으로, 카드나 현금 없이 휴대전화로 값을 치르는 것을 말한다.") is not None


# ── store ─────────────────────────────────────────────────────────────────

def test_store_roundtrip_keys_and_broken_file():
    with tempfile.TemporaryDirectory() as root:
        doc = store.load_day(root, DAY)
        assert doc["terms"] == []
        doc["terms"].append({"term": "Inflation", "reading": "인플레이션", "wikiTitle": "인플레이션"})
        store.save_day(root, DAY, doc)
        assert store.load_day(root, DAY)["terms"][0]["term"] == "Inflation"
        assert {"inflation", "인플레이션", "wiki:인플레이션"} <= store.known_keys(root, 2026)

        broken = store.day_path(root, date(2026, 9, 15))
        with open(broken, "w", encoding="utf-8") as f:
            f.write("{broken")
        assert store.load_day(root, date(2026, 9, 15))["terms"] == []
        assert os.path.exists(broken + ".broken"), "깨진 파일은 덮어쓰기 전에 옆에 남긴다"


# ── 한 회차 ───────────────────────────────────────────────────────────────

def test_fill_day_from_briefing_terms_without_article_text():
    with tempfile.TemporaryDirectory() as root:
        make_repo(root, news_terms=[
            ("인플레이션(Inflation)", "economy"), ("통화정책", "economy"),
            ("홍길동", "politics"), ("드립덕션(dripduction)", "science"),
            ("기업공개(IPO)", "it"), ("인사청문회", "politics"), ("머큐리", "world"),
            ("탄소중립", "science"), ("커넥톰(Connectome)", "it"),
        ])
        out = os.path.join(root, "data", "app_terms")
        store.save_day(out, date(2026, 9, 13), {"date": "2026-09-13", "runs": [],
                                                 "terms": [{"term": "통화정책", "reading": "", "wikiTitle": "통화정책"}]})
        chat = FakeChat()
        fake_wiki = FakeWiki(missing={"드립덕션", "dripduction"}, person={"홍길동"},
                             disambiguation={"머큐리"})
        result = pipeline.fill_day(DAY, repo_root=root, target=5, pool=one_key_pool(),
                                   chat=chat, wiki_lookup=fake_wiki, rss_loader=lambda: {})
        assert result["after"] == 5 and result["stopped"] == "목표 달성", result
        assert [kind for kind, _ in chat.calls] == ["meaning"], "브리핑 용어로 충분하면 고르기 호출은 없다"
        assert result["rejected"] == {"duplicate": 1, "no_wiki": 1, "person": 1, "disambiguation": 1}, result

        saved = store.load_day(out, DAY)
        assert len(saved["terms"]) == 5 and saved["runs"][-1]["added"] == 5
        first = saved["terms"][0]
        assert first["term"] == "Inflation" and first["reading"] == "인플레이션"
        assert first["url"].startswith("https://ko.wikipedia.org/wiki/") and first["categoryName"] == "경제"
        for entry in saved["terms"]:
            assert not {"link", "source", "definition", "ko_summary"} & set(entry), "기사 정보가 앱 데이터에 섞였다"
        categories = [entry["category"] for entry in saved["terms"]]
        assert categories[:3] == ["economy", "it", "politics"], "분야를 번갈아 저장해야 한다"

        again = FakeChat()
        second = pipeline.fill_day(DAY, repo_root=root, target=5, pool=one_key_pool(),
                                   chat=again, wiki_lookup=FakeWiki())
        assert again.calls == [] and second["added"] == 0 and second["stopped"].startswith("이미")


def test_fill_day_uses_article_list_when_briefing_terms_run_short():
    with tempfile.TemporaryDirectory() as root:
        make_repo(root, news_terms=[("인플레이션(Inflation)", "economy")], raw={
            "politics": {"domestic": [
                {"title": "국회, 인사청문회 증인 채택 무산", "summary": "여야 대치", "is_important": "True"}]},
            "economy": {"domestic": [
                {"title": "기준금리 동결…스태그플레이션 우려", "summary": "물가와 경기 둔화", "is_important": "False"}]},
        })
        chat = FakeChat(discoveries=[
            [{"id": 1, "term": "인사청문회"}, {"id": 1, "term": "양적완화"}],
            [{"id": 1, "term": "스태그플레이션(stagflation)"}, {"id": 9, "term": "번호 밖"}],
        ])
        result = pipeline.fill_day(DAY, repo_root=root, target=3, pool=one_key_pool(),
                                   chat=chat, wiki_lookup=FakeWiki(), rss_loader=lambda: {})
        assert result["after"] == 3, result
        assert result["via"] == ["news_terms", "raw"], result
        assert result["rejected"].get("not_in_article") == 1, "기사에 없는 '양적완화'는 막아야 한다"
        discovery_prompts = [prompt for kind, prompt in chat.calls if kind == "discovery"]
        assert "인플레이션" in discovery_prompts[0], "이미 실은 용어를 제외 목록으로 넘겨야 한다"
        terms = [entry["term"] for entry in store.load_day(os.path.join(root, "data", "app_terms"), DAY)["terms"]]
        assert terms == ["Inflation", "인사청문회", "Stagflation"], terms


def test_fill_day_collects_rss_only_when_article_list_is_missing():
    with tempfile.TemporaryDirectory() as root:
        make_repo(root)
        rss_calls = []

        def rss():
            rss_calls.append(1)
            return {"it": [{"title": "생성형 AI 저작권 소송 확산", "summary": "", "important": False}]}

        chat = FakeChat(discoveries=[[{"id": 1, "term": "생성형 AI"}]])
        result = pipeline.fill_day(DAY, repo_root=root, target=1, pool=one_key_pool(),
                                   chat=chat, wiki_lookup=FakeWiki(), rss_loader=rss)
        assert rss_calls == [1] and result["via"] == ["rss"] and result["after"] == 1, result

        make_repo(root, raw={"it": {"domestic": []}})
        rss_calls.clear()
        pipeline.fill_day(date(2026, 9, 14), repo_root=root, out_root=os.path.join(root, "other"),
                          target=1, pool=one_key_pool(), chat=FakeChat(), wiki_lookup=FakeWiki(),
                          rss_loader=rss)
        assert rss_calls == [], "기사 목록이 있으면 RSS 를 모으지 않는다"


def test_fill_day_saves_nothing_when_nvidia_is_down():
    with tempfile.TemporaryDirectory() as root:
        make_repo(root, news_terms=[("인플레이션(Inflation)", "economy")])
        result = pipeline.fill_day(DAY, repo_root=root, target=5, pool=one_key_pool(),
                                   chat=FakeChat(down=True), wiki_lookup=FakeWiki(),
                                   rss_loader=lambda: {})
        assert result["added"] == 0 and result["stopped"].startswith("후보 소진"), result
        assert not os.path.exists(result["path"]), "추가된 게 없으면 파일을 만들지 않는다(빈 커밋 방지)"


def test_fill_day_without_keys_does_nothing():
    with tempfile.TemporaryDirectory() as root:
        make_repo(root, news_terms=[("인플레이션(Inflation)", "economy")])
        chat = FakeChat()
        result = pipeline.fill_day(DAY, repo_root=root, pool=nim.KeyPool([]), chat=chat,
                                   wiki_lookup=FakeWiki())
        assert result["stopped"] == "NVIDIA 키 없음" and chat.calls == []


def test_fill_day_skips_terms_whose_meaning_failed():
    with tempfile.TemporaryDirectory() as root:
        make_repo(root, news_terms=[("인플레이션(Inflation)", "economy"), ("통화정책", "economy")])
        result = pipeline.fill_day(DAY, repo_root=root, target=5, pool=one_key_pool(),
                                   chat=FakeChat(fail_meanings={"통화정책"}), wiki_lookup=FakeWiki(),
                                   rss_loader=lambda: {})
        assert result["after"] == 1 and result["rejected"].get("no_meaning") == 1, result


def test_fill_day_uses_the_terms_own_category():
    with tempfile.TemporaryDirectory() as root:
        make_repo(root, news_terms=[("인플레이션(Inflation)", "politics"), ("기업공개(IPO)", "it")])
        chat = FakeChat(concepts={"Inflation (인플레이션)": "economy", "IPO (기업공개)": "banana"})
        pipeline.fill_day(DAY, repo_root=root, target=5, pool=one_key_pool(), chat=chat,
                          wiki_lookup=FakeWiki(), rss_loader=lambda: {})
        saved = {e["term"]: e for e in store.load_day(os.path.join(root, "data", "app_terms"), DAY)["terms"]}
        assert saved["Inflation"]["category"] == "economy" and saved["Inflation"]["categoryName"] == "경제"
        assert saved["IPO"]["category"] == "it", "모르는 분야 코드면 기사 분야를 그대로 쓴다"


def test_plan_run_finishes_before_the_app_opens():
    from datetime import datetime, timedelta, timezone
    kst = timezone(timedelta(hours=9))

    def at(hour, minute):
        return datetime(2026, 9, 14, hour, minute, tzinfo=kst)

    assert pipeline.plan_run(DAY, at(5, 50), 600) == (600, False, ""), "06:40 전에는 맥의 기사 목록을 기다린다"
    assert pipeline.plan_run(DAY, at(7, 15), 600) == (600, True, "")
    assert pipeline.plan_run(DAY, at(7, 45), 600) == (300, True, ""), "마감까지 남은 시간만 쓴다"
    budget, _, skip = pipeline.plan_run(DAY, at(7, 50), 600)
    assert budget == 0 and "마감" in skip
    assert pipeline.plan_run(DAY, at(17, 0), 600, explicit_date=True) == (600, True, ""), "날짜를 적으면 마감 없음"
    assert pipeline.plan_run(date(2026, 9, 13), at(17, 0), 600) == (600, True, "")


def test_summary_is_readable():
    text = pipeline.format_summary({"date": "2026-09-14", "before": 3, "after": 10, "added": 7,
                                    "via": ["news_terms", "raw"], "rejected": {"no_wiki": 4},
                                    "llm": "호출 3건", "stopped": "목표 달성"})
    assert "3개 → 10개" in text and "브리핑 용어 → 기사 목록" in text and "위키백과 문서 없음 4" in text


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"\n{len(tests)}개 통과")
