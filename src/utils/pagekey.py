"""
Page URL obfuscation
생성 페이지 파일명 끝에 난수 10글자를 붙여 URL 패턴만으로 접근할 수 없게 한다
(예: world-a7Kd2Xq9Lm.html). 날짜와 카테고리 이름만 알면 주소를 맞힐 수 있던 것을 막는 용도.

한계(반드시 인지할 것): 저장소가 public이면 난수를 몰라도 GitHub에서 파일 목록을
그대로 볼 수 있다. 이건 '주소 추측 차단'이지 접근 제어가 아니다. 진짜 비공개가
필요하면 저장소를 private으로 두고 다른 호스팅을 쓰거나 인증을 붙여야 한다.

날짜별로 결정론적이라 같은 날 다시 실행해도 같은 파일명이 나온다 — 안 그러면
재실행마다 새 파일이 쌓이고 이미 보낸 링크가 깨진다.
"""
import hashlib
import os
import secrets
import string

_ALPHABET = string.ascii_letters + string.digits
_TOKEN_LENGTH = 10
_SALT_FILE = "page_salt.txt"


def load_or_create_salt(data_dir: str) -> str:
    """
    난수의 기준이 되는 비밀 salt. 저장소에 커밋되면 의미가 없으므로
    .gitignore된 위치에 두거나 PAGE_SALT 환경변수(Actions Secret)로 준다.
    없으면 새로 만들어 저장한다.
    """
    env_salt = os.getenv("PAGE_SALT")
    if env_salt:
        return env_salt

    path = os.path.join(data_dir, _SALT_FILE)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            saved = f.read().strip()
            if saved:
                return saved

    salt = secrets.token_urlsafe(24)
    os.makedirs(data_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(salt)
    return salt


def page_token(salt: str, *parts: str) -> str:
    """(salt, 날짜, 페이지이름)에서 결정론적으로 뽑은 10글자 영숫자."""
    digest = hashlib.sha256(("|".join((salt,) + parts)).encode("utf-8")).digest()
    return "".join(_ALPHABET[b % len(_ALPHABET)] for b in digest[:_TOKEN_LENGTH])


def obfuscate(filename: str, salt: str, *parts: str) -> str:
    """'world.html' -> 'world-a7Kd2Xq9Lm.html'"""
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, "html"
    return f"{stem}-{page_token(salt, *parts, filename)}.{ext}"
