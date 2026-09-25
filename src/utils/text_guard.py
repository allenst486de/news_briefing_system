"""
모델 출력에 섞여 들어온 외국 문자를 잡아낸다.

대체 모델(muse-glimmer)이 한국어 문장 사이에 중국어·일본어를 섞어 쓰는 경우가 있다
(2026-09-26 발행분: '중국 지도자 접대를 앞두고对华 강경 발언을', '두 달간同居하며').
그대로 실리면 요약·카드·시사용어에 읽을 수 없는 글자가 남고, 카드 폰트에는 그 글자가 없어
빈칸이 된다. 이런 출력은 받지 않고 다시 요약하거나(기사) 버린다(용어).

한국 신문이 제목에 쓰는 한자(美·中·北·日·韓 등)는 허용한다. 그 밖의 한자는 원문에 있던
글자일 때만 허용한다 — 원문이 한자를 썼으면 요약에 옮겨 적을 수 있다.
""" 
import re

_CJK = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
PRESS_HANJA = set("美中日北韓英佛獨露伊印與野靑靑檢軍警朝前現新舊故親反非核外總黨政法")


def foreign_leak(text: str, source: str = "") -> bool:
    """원문(source)에 없던 중국어·일본어 글자가 섞였는가"""
    for char in _CJK.findall(text or ""):
        if _KANA.match(char):
            if char not in (source or ""):
                return True
            continue
        if char in PRESS_HANJA or char in (source or ""):
            continue
        return True
    return False
