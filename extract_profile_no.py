"""TVING 웹 로그인 후 지정한 값을 추출한다 (기본: profileNo).

실행:
    python extract_profile_no.py --id <아이디> --password <비밀번호>
    python extract_profile_no.py --target profile_no --login-type cj-one

출력:
    profile_no: 12345678

찾을 값은 config/<env>.yml 의 targets 에 정의한다. 다른 값이 필요하면
target 을 추가하고 --target 으로 지정하면 코드 수정 없이 동작한다.
"""
from __future__ import annotations

import argparse
import os
import sys

from playwright.sync_api import sync_playwright

from extractors import (
    ConfigError,
    LoginFailed,
    NotFoundError,
    ValueFinder,
    available_envs,
    load_config,
    load_env_file,
    login,
)

DEFAULT_TARGET = "profile_no"


def parse_args() -> argparse.Namespace:
    envs = available_envs()
    parser = argparse.ArgumentParser(
        description="TVING 로그인 후 지정한 값을 추출한다 (기본: profileNo)."
    )
    parser.add_argument("--id", default=os.environ.get("TVING_ID"), help="아이디 (기본: $TVING_ID)")
    parser.add_argument(
        "--password",
        default=os.environ.get("TVING_PASSWORD"),
        help="비밀번호 (기본: $TVING_PASSWORD)",
    )
    parser.add_argument(
        "--login-type",
        default=os.environ.get("TVING_LOGIN_TYPE", "tving"),
        help="로그인 유형. 아이디만으로는 판별할 수 없어 지정해야 한다 (기본: tving)",
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("TVING_TARGET", DEFAULT_TARGET),
        help=f"추출 대상. config 의 targets 에 정의된 이름 (기본: {DEFAULT_TARGET})",
    )
    parser.add_argument("--show", action="store_true", help="브라우저를 화면에 띄운다")
    parser.add_argument(
        "--env",
        default=os.environ.get("TVING_ENV", "prod"),
        choices=envs or None,
        help=f"설정 파일 선택. config/<env>.yml 을 읽는다 (기본: prod, 가능: {', '.join(envs) or '없음'})",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> tuple[str, str]:
    """로그인 → 대상 화면 → 값 추출. 실패는 예외로 올린다."""
    config = load_config(args.env)
    target = config.target(args.target)

    with sync_playwright() as playwright:
        browser = getattr(playwright, config.browser_type).launch(
            headless=config.headless and not args.show
        )
        context = browser.new_context(locale=config.locale)
        context.set_default_timeout(config.timeout_ms)
        page = context.new_page()

        try:
            # 캡처는 이동 전에 시작한다 — 응답은 흘러간 뒤 다시 못 잡는다.
            finder = ValueFinder(page, config, target)
            finder.start_capture()

            login(page, config, args.id, args.password, args.login_type, target.path)

            # networkidle 을 쓰지 않는 이유: 스트리밍 서비스는 배경 요청이
            # 계속 흘러 networkidle 이 영영 안 올 수 있다.
            page.goto(config.target_url(target), wait_until="domcontentloaded")
            if "/account/login" in page.url:
                raise NotFoundError("대상 화면 진입 시 로그인 화면으로 돌아갔습니다 (세션 유실).")

            page.wait_for_timeout(config.settle_ms)  # API 응답 도착 여유
            value = finder.find()

            # 서로 다른 값이 잡혔다면 조용히 넘기지 않는다. 키 이름으로 찾는 방식은
            # 무관한 응답(추천·이벤트 등)에 실린 다른 값을 잡을 수 있어,
            # 어느 것이 맞는지 사람이 확인해야 한다.
            for other, endpoint in finder.conflicts():
                print(f"[경고] 다른 값도 발견됨: {other} ({endpoint})", file=sys.stderr)

            return target.name, value
        finally:
            context.close()
            browser.close()


def main() -> int:
    # .env 를 argparse 보다 먼저 읽어야 한다. 인자 기본값이 os.environ 에서
    # 오기 때문에, 순서가 뒤집히면 .env 값이 반영되지 않는다.
    load_env_file()
    args = parse_args()

    if not args.id or not args.password:
        print(
            "아이디/비밀번호가 필요합니다.\n"
            "  python extract_profile_no.py --id <아이디> --password <비밀번호>\n"
            "  또는 환경변수 TVING_ID / TVING_PASSWORD 설정 (.env 도 읽습니다)",
            file=sys.stderr,
        )
        return 2

    try:
        name, value = run(args)
    except ConfigError as error:
        print(f"설정 오류: {error}", file=sys.stderr)
        return 2
    except (LoginFailed, NotFoundError) as error:
        print(f"실패: {error}", file=sys.stderr)
        return 1

    print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
