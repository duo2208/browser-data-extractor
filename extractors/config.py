"""설정 로드 — config/<env>.yml + 시크릿은 환경변수.

구조와 시크릿을 분리한다.

  - config/*.yml  : URL·타임아웃·추출 대상 정의. 커밋되고 리뷰된다.
  - 환경변수/.env : 아이디·비밀번호. 커밋되면 회수가 안 된다.

추출 대상(targets)도 설정으로 뺐다. 코드가 'profileNo' 를 모르게 해서,
다른 값을 찾아야 할 때 yml 에 target 을 추가하는 것으로 끝나게 하기 위함이다.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class ConfigError(RuntimeError):
    """설정을 읽을 수 없을 때. '검증 실패'가 아니라 '실행 전 오류'로 구분한다."""


def available_envs() -> list[str]:
    """config/ 에 있는 환경 목록. --env 선택지와 에러 메시지에 쓴다.

    선택지를 코드에 하드코딩하지 않는 이유: yml 을 추가하면 그것만으로
    새 환경이 생기게 하려고. 파일과 코드를 양쪽에서 고치면 어긋난다.
    """
    if not CONFIG_DIR.is_dir():
        return []
    return sorted(path.stem for path in CONFIG_DIR.glob("*.yml"))


def load_env_file() -> None:
    """.env 가 있으면 읽는다. 없으면 조용히 넘어간다.

    이미 설정된 환경변수는 덮어쓰지 않는다 — CI Secrets 로 주입한 값이
    저장소에 남아 있는 .env 에 밀리면 안 되기 때문.
    """
    path = PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Target:
    """무엇을 어디서 찾을지에 대한 정의.

    이 객체가 있으면 추출 모듈은 'profileNo' 라는 이름을 몰라도 된다.
    찾을 키, 검증 규칙, endpoint 우선순위가 전부 여기 담긴다.
    """

    name: str
    path: str                          # 값을 찾으러 진입할 화면 경로
    keys: tuple[str, ...]              # 응답/DOM 에서 찾을 키 이름
    pattern: re.Pattern[str]           # 값 형식 검증
    url_pattern: Optional[re.Pattern[str]]  # URL 에 실린 경우를 잡는 패턴
    endpoint_hints: tuple[str, ...]    # 우선할 endpoint 순서
    json_path: tuple[str, ...]         # 확인된 응답 경로 (예: body.profile.profileNo)


@dataclass(frozen=True)
class Config:
    environment: str
    base_url: str
    login_paths: dict[str, str]
    browser_type: str
    headless: bool
    locale: str
    timeout_ms: int
    hydration_selectors: tuple[str, ...]
    settle_ms: int
    login_failure_text: str
    submit_wait_ms: int
    targets: dict[str, Target]

    def target(self, name: str) -> Target:
        if name not in self.targets:
            raise ConfigError(
                f"추출 대상 {name!r} 이 {self.environment} 설정에 없습니다. "
                f"가능한 값: {', '.join(sorted(self.targets))}"
            )
        return self.targets[name]

    def target_url(self, target: Target) -> str:
        return f"{self.base_url}{target.path}"

    def login_url(self, login_type: str, return_path: str) -> str:
        """입력폼 URL.

        returnUrl 을 붙여 로그인 직후 대상 화면으로 돌아오게 한다.
        '로그인 → 별도 이동' 2단계가 1단계로 줄어 중간 리다이렉트를 덜 탄다.
        """
        if login_type not in self.login_paths:
            raise ConfigError(
                f"로그인 유형 {login_type!r} 이 {self.environment} 설정에 없습니다. "
                f"가능한 값: {', '.join(sorted(self.login_paths))}"
            )
        destination = f"{self.base_url}{return_path}"
        path = self.login_paths[login_type]
        return f"{self.base_url}{path}?returnUrl={quote(destination, safe='')}"


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"설정의 {name!r} 항목이 올바르지 않습니다 (dict 여야 함)")
    return value


def _build_target(name: str, raw: Any, path_label: Path) -> Target:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path_label} 의 targets.{name} 이 올바르지 않습니다 (dict 여야 함)")

    keys = tuple(raw.get("keys") or ())
    if not keys:
        raise ConfigError(f"{path_label} 의 targets.{name}.keys 가 비어 있습니다.")

    target_path = raw.get("path")
    if not target_path:
        raise ConfigError(f"{path_label} 의 targets.{name}.path 가 없습니다.")

    # 패턴은 로드 시점에 컴파일한다. 잘못된 정규식을 실행 도중이 아니라
    # 시작할 때 잡아야 원인이 분명해진다.
    try:
        pattern = re.compile(str(raw.get("pattern", r"^.+$")))
        url_raw = raw.get("url_pattern")
        url_pattern = re.compile(str(url_raw), re.IGNORECASE) if url_raw else None
    except re.error as error:
        raise ConfigError(f"{path_label} 의 targets.{name} 정규식이 올바르지 않습니다: {error}") from error

    # json_path 는 "body.profile.profileNo" 형태로 쓴다. 확인된 경로가 있으면
    # 키 이름 탐색보다 이쪽을 먼저 쓴다 — 같은 응답 안에 같은 키가 여러 개
    # 있을 때(프로필 목록 등) 어느 것이 맞는지 순서에 기대지 않기 위해서다.
    raw_json_path = raw.get("json_path") or ""
    json_path = tuple(part for part in str(raw_json_path).split(".") if part)

    return Target(
        name=name,
        path=str(target_path),
        keys=keys,
        pattern=pattern,
        url_pattern=url_pattern,
        endpoint_hints=tuple(raw.get("endpoint_hints") or ()),
        json_path=json_path,
    )


def load_config(env: str) -> Config:
    """config/<env>.yml 을 읽어 Config 를 만든다.

    파일이 없으면 조용히 기본값으로 떨어지지 않고 즉시 끊는다. 오타 난 환경
    이름으로 엉뚱한 곳을 치는 사고를 막기 위해서다.
    """
    path = CONFIG_DIR / f"{env.lower()}.yml"
    if not path.exists():
        envs = available_envs()
        raise ConfigError(
            f"설정 파일을 찾을 수 없습니다: {path}\n"
            f"  사용 가능한 환경: {', '.join(envs) if envs else '(config/*.yml 없음)'}"
        )

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    service = _section(data, "service")
    browser = _section(data, "browser")
    extract = _section(data, "extract")
    login = _section(data, "login")
    raw_targets = _section(data, "targets")

    base_url = service.get("base_url")
    if not base_url:
        raise ConfigError(f"{path} 에 service.base_url 이 없습니다.")

    login_paths = service.get("login_paths") or {}
    if not login_paths:
        raise ConfigError(f"{path} 에 service.login_paths 가 없습니다.")

    if not raw_targets:
        raise ConfigError(f"{path} 에 targets 가 없습니다. 최소 1개는 정의해야 합니다.")

    # 환경변수 오버라이드 — 값 하나만 잠깐 바꿔 돌릴 때가 있어서 열어 둔다.
    # yml 이 기본이고 환경변수가 우선이다.
    if override := os.environ.get("TVING_BASE_URL"):
        base_url = override
    headless = browser.get("headless", True)
    if (raw := os.environ.get("HEADLESS")) is not None:
        headless = raw.strip().lower() in {"1", "true", "yes", "y", "on"}

    return Config(
        environment=str(data.get("environment", env)),
        base_url=str(base_url).rstrip("/"),
        login_paths={str(k): str(v) for k, v in login_paths.items()},
        browser_type=str(browser.get("type", "chromium")),
        headless=bool(headless),
        locale=str(browser.get("locale", "ko-KR")),
        timeout_ms=int(browser.get("timeout", 15000)),
        hydration_selectors=tuple(extract.get("hydration_selectors") or ()),
        settle_ms=int(extract.get("settle_ms", 2000)),
        login_failure_text=str(login.get("failure_text", "")),
        submit_wait_ms=int(login.get("submit_wait_ms", 2000)),
        targets={
            str(name): _build_target(str(name), raw, path)
            for name, raw in raw_targets.items()
        },
    )
