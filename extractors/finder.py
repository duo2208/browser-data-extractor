"""웹 페이지에서 값을 찾는 공통 엔진 — Network / URL / DOM.

■ 무엇을 찾는지는 이 모듈이 모른다
찾을 키·검증 규칙·endpoint 우선순위는 Target(설정)이 들고 온다. 그래서
profileNo 든 userNo 든 같은 코드로 처리되고, 대상이 늘어도 여기는 안 바뀐다.

■ 왜 한 곳이 아니라 3개 소스인가
이런 식별자는 화면에 보여주려고 만든 값이 아니라 내부 키라, 어디에 드러나는지가
서비스 구현에 따라 다르다. 한 곳만 보면 그 한 곳이 바뀌는 순간 추출이 끊긴다.

  1) network — 페이지가 호출하는 API 응답. UI 구조에 덜 의존한다.
  2) url     — 쿼리스트링·경로에 실린 경우. 파싱 비용이 가장 작다.
  3) dom     — 하이드레이션 페이로드. 렌더링 구조 변경에 가장 약해서 마지막.

이 순서는 절대적인 신뢰도 순서가 아니라 탐색 순서다. 어떤 API 의 어떤 객체인지
확인되지 않은 network 값이라면, 화면이 명시하는 url 값보다 신뢰도가 낮을 수도 있다.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from playwright.sync_api import Page, Response

from extractors.config import Config, Target

MAX_DEPTH = 12  # 비정상적으로 깊거나 순환하는 응답 방어


class NotFoundError(RuntimeError):
    """세 소스 어디에서도 값을 찾지 못했을 때.

    무엇을 봤는지를 메시지에 담는다. 실패 리포트에서 확인이 어려운 것은
    '못 찾음' 자체가 아니라 '어디까지 확인했는지 모르는 것'이다.
    """


def normalize(value: Any, target: Target) -> Optional[str]:
    """값을 문자열로 정규화하고 형식을 검증한다.

    None / "" / "null" / "undefined" 가 성공으로 통과하는 것을 막는 관문.
    식별자는 앞자리 0 이 의미를 가질 수 있어 int 로 변환하지 않고 문자열로 다룬다.
    """
    if isinstance(value, bool):  # bool 은 int 의 subclass 라 먼저 걸러야 한다
        return None
    if isinstance(value, int):
        candidate = str(value)
    elif isinstance(value, str):
        candidate = value.strip()
    else:
        return None
    return candidate if target.pattern.match(candidate) else None


def find_by_path(payload: Any, target: Target) -> Optional[str]:
    """확인된 경로에서 값을 꺼낸다. 경로가 없거나 안 맞으면 None.

    왜 경로를 우선하는가: 같은 응답 안에 같은 키가 여러 번 나올 수 있다.
    실제 TVING 응답에는 현재 프로필(body.profile)과 계정에 딸린 프로필 목록
    (body.profileList[])이 함께 담겨 서로 다른 profileNo 가 3개 들어 있었다.
    키 이름만으로 찾으면 '먼저 나온 것'이 답이 되는데, 그건 서버가 키 순서를
    바꾸는 순간 다른 프로필 값으로 조용히 바뀐다는 뜻이다.
    """
    if not target.json_path:
        return None

    node: Any = payload
    for part in target.json_path:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return normalize(node, target)


def find_in_json(payload: Any, target: Target, depth: int = 0) -> Optional[str]:
    """중첩 JSON 을 훑어 target 의 키를 찾는다.

    응답이 어떻게 래핑되는지(`{body: {result: [...]}}` 등) 미리 알 수 없으므로
    경로를 고정하지 않고 키 이름으로 찾는다. 스키마가 바뀌어도 키가 살아 있으면 잡힌다.
    """
    if depth > MAX_DEPTH:
        return None

    lowered = {key.lower() for key in target.keys}

    if isinstance(payload, dict):
        # 얕은 곳의 값이 더 정확하므로 같은 깊이에서 직접 매칭을 먼저 시도한다.
        for key, value in payload.items():
            if isinstance(key, str) and key.lower() in lowered:
                if found := normalize(value, target):
                    return found
        for value in payload.values():
            if found := find_in_json(value, target, depth + 1):
                return found

    elif isinstance(payload, list):
        for item in payload:
            if found := find_in_json(item, target, depth + 1):
                return found

    return None


class ValueFinder:
    """페이지 이동 *전에* 만들어서 네트워크 응답을 놓치지 않게 한다.

        finder = ValueFinder(page, config, target)
        finder.start_capture()      # 이동 전에 리스너 부착
        page.goto(url)              # 이 사이에 흐른 응답이 캡처된다
        value = finder.find()
    """

    def __init__(self, page: Page, config: Config, target: Target) -> None:
        self.page = page
        self.config = config
        self.target = target
        self._captured: list[tuple[str, str]] = []  # (값, 발견한 endpoint)
        self._seen_endpoints: list[str] = []

    # -- network ------------------------------------------------------------
    def start_capture(self) -> None:
        """response 리스너 부착. 반드시 페이지 이동 전에 호출.

        sleep 으로 기다리지 않고 리스너로 받는 이유: 응답이 언제 오는지 모르는데
        고정 시간을 자면 느릴 땐 놓치고 빠를 땐 낭비다. 이벤트로 받으면 둘 다 없다.
        """
        self.page.on("response", self._on_response)

    def _on_response(self, response: Response) -> None:
        # 관찰은 부수효과 — 여기서 예외가 나도 본류를 깨면 안 된다.
        try:
            if "json" not in (response.header_value("content-type") or "").lower():
                return
            self._seen_endpoints.append(response.url)
            payload = response.json()
            # 확인된 경로를 먼저 본다. 없으면 키 이름 탐색으로 떨어진다.
            found = find_by_path(payload, self.target) or find_in_json(payload, self.target)
            if found:
                # endpoint 를 함께 남긴다. 어느 응답에서 나온 값인지 모르면
                # 값이 엇갈렸을 때 무엇이 맞는지 판단할 수 없다.
                self._captured.append((found, response.url))
        except Exception:
            # 응답 body 를 못 읽는 경우(리다이렉트/스트림/이미 소비됨)는 정상 범주.
            return

    def _rank(self, url: str) -> int:
        """endpoint 우선순위. 낮을수록 먼저.

        키 이름만으로 찾으면 추천·이벤트 같은 무관한 응답에 실린 다른 값을
        잡을 수 있다. 관련 endpoint 를 앞세워 오탐 확률을 낮춘다.
        """
        lowered = url.lower()
        for index, hint in enumerate(self.target.endpoint_hints):
            if hint.lower() in lowered:
                return index
        return len(self.target.endpoint_hints)

    # -- url / dom ----------------------------------------------------------
    def _from_url(self) -> Optional[str]:
        if self.target.url_pattern is None:
            return None
        match = self.target.url_pattern.search(self.page.url)
        if not match:
            return None
        return normalize(match.group(1), self.target)

    def _from_dom(self) -> Optional[str]:
        # 하이드레이션 페이로드 — 서버 데이터가 script 태그에 JSON 으로 실린다.
        # 화면에 안 보여도 값은 DOM 안에 있다.
        for selector in self.config.hydration_selectors:
            try:
                for element in self.page.locator(selector).all():
                    raw = element.text_content()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if found := find_in_json(payload, self.target):
                        return found
            except Exception:
                continue
        return None

    # -- 판정 ---------------------------------------------------------------
    def find(self) -> str:
        """network → url → dom 순으로 탐색. 전부 실패하면 무엇을 봤는지 담아 raise."""
        if self._captured:
            # endpoint 우선순위가 높은 값을 고른다. 첫 번째로 도착한 값이
            # 반드시 맞는 값은 아니다 — 추천 API 가 먼저 응답할 수도 있다.
            return min(self._captured, key=lambda item: self._rank(item[1]))[0]
        if found := self._from_url():
            return found
        if found := self._from_dom():
            return found
        raise NotFoundError(self._failure_report())

    def conflicts(self) -> list[tuple[str, str]]:
        """network 에서 서로 다른 값이 잡혔다면 (값, endpoint) 목록을 돌려준다.

        값이 하나뿐이면 빈 목록. 엇갈린다는 건 추출 버그가 아니라 '어느 것이
        맞는 값인지 아직 모른다'는 신호라, 조용히 넘기지 않고 드러낸다.
        """
        if len({value for value, _ in self._captured}) <= 1:
            return []
        return list(self._captured)

    def _failure_report(self) -> str:
        shown = self._seen_endpoints[:10]
        endpoints = (
            "\n".join(f"      - {url}" for url in shown)
            if shown
            else "      (JSON 응답 없음)"
        )
        more = (
            f"\n      ... 외 {len(self._seen_endpoints) - 10}건"
            if len(self._seen_endpoints) > 10
            else ""
        )
        return (
            f"{self.target.name} 을(를) 찾지 못했습니다 (network / url / dom 모두 실패).\n"
            f"  현재 URL: {self.page.url}\n"
            f"  찾은 키 후보: {', '.join(self.target.keys)}\n"
            f"  검사한 JSON 응답 {len(self._seen_endpoints)}건:\n{endpoints}{more}\n"
            "  → 화면 진입이 실제로 성공했는지 --show 로 확인하고,\n"
            f"     위 목록에서 값을 내려주는 응답을 찾아 config 의\n"
            f"     targets.{self.target.name}.keys 를 실제 키 이름으로 맞추세요."
        )
