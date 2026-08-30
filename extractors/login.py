"""로그인 + 성공 여부 판정.

■ '로그인 성공'을 무엇으로 판정하는가
버튼을 눌렀다는 사실은 성공이 아니다. 자동화에서 가장 흔한 거짓 통과가
'클릭은 됐으니 됐겠지' 이고, 실제로는 비밀번호 오류·추가 인증 때문에 같은
자리에 남아 있는 경우가 많다.

그래서 **실패 문구를 먼저** 보고, 그다음 로그인 경로를 벗어났는지 본다.
순서가 반대면 실패 원인이 '요소를 못 찾음' 타임아웃으로 뭉개져서, 리포트만
보고는 왜 실패했는지 알 수 없게 된다.
"""
from __future__ import annotations

from playwright.sync_api import Page

# 입력 필드 셀렉터.
#
# 이 폼에는 id 도 data-testid 도 없어서 name 으로 잡는다. name 은 폼 전송 키라
# 서버와 계약처럼 묶여 있어, 화면 문구인 placeholder 보다 안정적이다.
#
# get_by_label 은 쓰지 않는다. 같은 화면의 aria-label="티빙 아이디 회원가입"
# 버튼이 부분 매칭으로 잘못 잡히기 때문이다. 접근성 조회도 이름이 겹치면
# 틀린 요소를 집는다.
#
# CSS 클래스도 제외했다. Tailwind 유틸리티 + 해시 조합이라 배포 한 번에 깨진다.
ID_INPUT = "input[name='id']"
PW_INPUT = "input[name='password']"
SUBMIT_BUTTON_TEXT = "로그인"


class LoginFailed(RuntimeError):
    """로그인이 성공하지 못했을 때. 값 추출로 넘어가면 안 되므로 여기서 끊는다."""


def login(
    page: Page, config, user_id: str, password: str, login_type: str, return_path: str
) -> None:
    """로그인하고 성공 여부까지 확인한다. 실패 시 LoginFailed.

    return_path 는 로그인 성공 후 돌아올 화면이다. 추출 대상마다 진입 화면이
    다를 수 있어 호출하는 쪽이 넘긴다.
    """
    page.goto(config.login_url(login_type, return_path), wait_until="domcontentloaded")

    page.locator(ID_INPUT).fill(user_id)
    page.locator(PW_INPUT).fill(password)
    page.get_by_role("button", name=SUBMIT_BUTTON_TEXT, exact=True).first.click()

    # (1) 부정 신호 먼저 — 실패 문구가 떴으면 즉시 끊는다.
    page.wait_for_timeout(config.submit_wait_ms)
    if page.get_by_text(config.login_failure_text, exact=False).count() > 0:
        raise LoginFailed(
            "로그인 실패: 서버가 자격증명을 거부했습니다.\n"
            f"  아이디/비밀번호와 로그인 유형(--login-type "
            f"{'/'.join(sorted(config.login_paths))})을 확인하세요.\n"
            "  서비스는 이 둘을 같은 문구로 응답하므로 양쪽 다 점검해야 합니다."
        )

    # (2) 긍정 신호 — 로그인 경로를 벗어났는지.
    #     wait_for_url 로 '상태'를 기다린다. 고정 대기는 느린 환경에선 부족하고
    #     빠른 환경에선 낭비라 양쪽 모두 손해다.
    try:
        page.wait_for_url(lambda url: "/account/login" not in url, timeout=config.timeout_ms)
    except Exception as error:
        raise LoginFailed(
            "로그인 실패: 제출 후에도 로그인 페이지에 머물러 있습니다.\n"
            "  자격증명 오류 / 추가 인증(캡차·2FA) 가능성이 있습니다.\n"
            "  --show 로 재실행해 화면을 직접 확인하세요."
        ) from error
