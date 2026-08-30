# TVING 사전과제 — profileNo 추출

웹 로그인 후 마이페이지에서 `profileNo`를 추출하는 CLI 도구입니다.

```text
tving_extract/
├── extract_profile_no.py     진입점 (CLI)
├── extractors/               값 탐색 공통 모듈
│   ├── config.py             설정 및 추출 대상 로드
│   ├── login.py              로그인 및 성공 여부 판정
│   └── finder.py             값 탐색 (Network / URL / DOM)
├── config/
│   └── prod.yml              base_url, timeout, 추출 대상 정의
├── pyproject.toml            의존성 정의
├── uv.lock                   의존성 버전 고정
└── .env.example              자격증명 템플릿
```

`extractors`는 특정 값에 종속되지 않는 공통 모듈입니다. 무엇을 찾을지는 설정의 `targets`에서 정의하므로, 다른 값이 필요한 경우에도 모듈 코드는 변경하지 않습니다.

<br>

## 1. 실행

```bash
uv sync
uv run playwright install chromium
uv run extract-profile-no --id <아이디> --password <비밀번호>
```

성공 시 다음과 같이 출력됩니다.

```text
profile_no: 12345678
```

`uv.lock`으로 의존성 버전을 고정해 실행 환경에 따른 차이를 최소화했습니다.

CJ ONE 연동 계정은 `--login-type`으로 로그인 경로를 지정할 수 있습니다.

```bash
uv run extract-profile-no --login-type cj-one --id <아이디> --password <비밀번호>
```

브라우저 동작을 직접 확인하려면 `--show` 옵션을 사용합니다.

```bash
uv run extract-profile-no --show --id <아이디> --password <비밀번호>
```

자격증명을 매번 입력하지 않으려면 `.env.example`을 복사해 `.env`에 값을 채웁니다.

```bash
cp .env.example .env
uv run extract-profile-no
```

`uv`를 사용하지 않는 경우에는 다음과 같이 실행할 수 있습니다.

```bash
pip install playwright pyyaml
playwright install chromium
python extract_profile_no.py --id <아이디> --password <비밀번호>
```

| 옵션 | 설명 |
|---|---|
| `--id` / `--password` | 로그인 자격증명 |
| `--login-type` | `tving` / `cj-one`. 기본값 `tving` |
| `--show` | 브라우저를 화면에 표시 |
| `--target` | 추출 대상. 설정의 `targets`에 정의된 이름. 기본값 `profile_no` |
| `--env` | 설정 파일 선택. `config/<env>.yml`을 읽음. 기본값 `prod` |

자격증명은 CLI 인자, `TVING_ID` / `TVING_PASSWORD` 환경변수, `.env` 순으로 조회합니다. 이미 설정된 환경변수는 `.env` 값으로 덮어쓰지 않으므로, CI에서 Secret으로 주입한 값이 저장소에 남은 `.env`에 밀리지 않습니다.

종료 코드는 다음과 같이 구분합니다.

```text
0  성공
1  로그인 또는 profileNo 추출 실패
2  설정 오류
```

설정 오류를 별도로 구분한 이유는 실제 테스트 실패가 아니라 실행 전 환경 문제이기 때문입니다. CI에서도 실행 환경 오류와 기능 검증 실패를 분리해 확인할 수 있습니다.

로그인 실패와 추출 실패를 같은 코드로 둔 것은, 프로세스를 호출하는 쪽에서는 둘 다 실행 실패로 동일하게 처리되기 때문입니다. 세부 원인은 stderr 메시지와 예외 타입(`LoginFailed` / `NotFoundError`)으로 구분하며, CI에서 분기가 필요해지면 별도 코드로 확장할 수 있습니다.

<br>

## 2. 설정 구조

설정은 **공개 가능한 실행 구조**와 **시크릿 정보**를 분리했습니다.

| 구분 | 위치 | 내용 |
|---|---|---|
| 구조 | `config/*.yml` | `base_url`, timeout, 추출 대상 정의 |
| 시크릿 | 환경변수 / `.env` | 아이디, 비밀번호 |


<br>

- 자격증명은 저장소에 커밋되지 않도록 설정 파일과 분리했습니다. CI에서는 동일한 이름의 Secret으로 주입하면 코드 수정 없이 동작합니다.
- 반대로 `base_url`과 같은 환경 설정을 모두 환경변수로 관리하면 실행 명령이 길어지고 어떤 환경에서 실행했는지 추적하기 어려워집니다. 따라서 기본 설정은 YAML에 두고 필요한 값만 `TVING_BASE_URL` / `HEADLESS` 환경변수로 override하도록 구성했습니다.
- 환경을 추가하려면 `config/`에 `<env>.yml` 파일을 추가하면 됩니다. `--env` 선택지는 실제 존재하는 설정 파일을 기준으로 생성하므로 환경 목록을 코드에 중복 관리하지 않습니다.

<br>

```bash
$ uv run extract-profile-no --env staging --id x --password y

error: argument --env: invalid choice: 'staging' (choose from 'prod')
```

잘못된 환경 이름으로 의도하지 않은 서비스에 접근하는 것을 방지하기 위한 처리입니다.

현재 과제 범위에서는 `prod` 환경만 포함했습니다.

<br>

### 추출 대상 정의

찾을 값 역시 코드가 아니라 설정에 정의했습니다. `extractors` 모듈은 `profileNo`라는 이름을 알지 못하며, 어떤 키를 어떤 규칙으로 찾을지는 `targets`에서 결정합니다.

```yaml
targets:
  profile_no:
    path: /my                      # 값을 찾으러 진입할 화면
    keys: [profileNo, profile_no]  # 응답에서 찾을 키
    pattern: "^[0-9]+$"            # 값 형식 검증
    endpoint_hints: [/profile, /my]  # 우선 확인할 endpoint
```

다른 값이 필요한 경우 `targets`에 항목을 추가하고 `--target`으로 지정하면 모듈 코드는 수정하지 않습니다. 값마다 형식이 다르므로 검증 규칙도 대상별로 지정합니다.

과제 요구사항은 `profileNo` 단일 값이므로 한 번에 하나의 대상만 추출합니다.

<br>

## 3. 추출 전략

`profileNo`는 화면 표시용 값이 아니라 프로필 식별에 사용되는 내부 값이므로, 실제 서비스 구현에 따라 노출 위치가 달라질 수 있습니다.

특정 DOM이나 단일 API에만 의존하지 않고 다음 순서로 탐색합니다.

| 탐색 순서 | 소스 | 확인 대상 | 이유 |
|---|---|---|---|
| 1 | Network | 마이페이지 진입 과정에서 발생하는 JSON API 응답 | UI 구조에 덜 의존하고 원본 데이터에 가까워 우선 탐색 |
| 2 | URL | query string 또는 path에 포함된 프로필 값 | 별도 파싱 비용이 작고 현재 화면 context와 직접 연결됨 |
| 3 | DOM | `__NEXT_DATA__` 등 페이지 hydration 데이터 | 렌더링 구조나 프레임워크 구현 변경의 영향을 가장 크게 받음 |

이 순서는 절대적인 신뢰도 순서가 아니라 탐색 순서입니다. 어떤 API의 어떤 객체인지 확인되지 않은 Network 값이라면, 현재 화면이 명시하는 URL 값보다 오히려 신뢰도가 낮을 수 있습니다.

실제 확인 결과 `profileNo`는 Network 응답에서만 발견되었고, URL과 DOM에서는 노출되지 않았습니다. 세 소스를 모두 탐색하도록 구성한 것이 실제로 유효했던 부분입니다.

### 실행 순서와 판정 순서

Network 응답은 페이지 이동 과정에서 한 번 지나가면 다시 관측할 수 없으므로, response listener는 마이페이지 이동 전에 등록합니다.

이후 수집된 결과를 기준으로 Network → URL → DOM 순서로 최종 값을 판정합니다.

<br>

## 4. 그 외

구현 세부 사항과 과제 수행 중 확인한 내용입니다.

<br>

### 응답 스키마 처리

정상 로그인 세션에서 실제 응답 구조를 확인했습니다.

| 항목 | 확인 결과 |
|---|---|
| endpoint | `api.tving.com/v2/user/info` |
| 응답 경로 | `body.profile.profileNo` |
| 값 타입 | 문자열 |

확인 과정에서 이 응답에 `profileNo`가 **하나가 아니라는 점**을 발견했습니다.

```json
{
  "body": {
    "profile":     { "profileNo": "100000001" },
    "profileList": [
      { "profileNo": "100000001" },
      { "profileNo": "200000002" },
      { "profileNo": "300000003" }
    ]
  }
}
```

현재 선택된 프로필(`body.profile`)과 계정에 등록된 프로필 목록(`body.profileList`)이 함께 내려오며, 실제로 서로 다른 값 3개가 포함되어 있었습니다.

키 이름만으로 재귀 탐색할 경우 먼저 발견된 값이 결과가 되므로, 서버가 응답 키 순서를 변경하면 다른 프로필의 값이 조용히 반환될 수 있습니다. 실제로 키 순서를 바꿔 확인한 결과 값이 `200000002`로 달라졌습니다.

따라서 확인된 경로를 설정에 고정했습니다.

```yaml
json_path: body.profile.profileNo
```

경로 지정 시에는 키 순서와 무관하게 동일한 값을 반환합니다. 다만 응답 구조가 변경될 가능성을 고려해 키 기반 재귀 탐색을 fallback으로 유지하며, 경로를 찾지 못한 경우에만 사용합니다.

값이 여러 endpoint에서 서로 다르게 발견되는 경우에는 경고를 출력합니다.

```text
[경고] 다른 값도 발견됨: 111111 (https://api.tving.com/recommendation/v1/home)
```

이번 확인에서는 `profileNo`를 포함한 응답이 `user/info` 한 건이었고 값 충돌은 발생하지 않았습니다.

<br>

### 값 검증

값을 발견했다는 사실만으로 성공 처리하지 않습니다.

`null`, 빈 문자열, `"undefined"` 등 유효하지 않은 값은 제외하고 숫자 형식인지 검증합니다.

`profileNo`는 식별자이므로 앞자리 `0`이 의미를 가질 가능성을 고려해 정수형으로 변환하지 않고 문자열 상태를 유지합니다.

세 소스에서 모두 값을 찾지 못한 경우에는 단순 실패로 처리하지 않고 확인한 범위를 함께 출력합니다.

```text
profile_no 을(를) 찾지 못했습니다 (network / url / dom 모두 실패).
  현재 URL: https://www.tving.com/my
  찾은 키 후보: profileNo, profile_no, profileno
  검사한 JSON 응답 12건:
      - https://gw.tving.com/...
```

실패 리포트에서 확인이 어려운 것은 값을 찾지 못했다는 사실 자체보다 어느 범위까지 확인했는지 알 수 없는 경우이므로, 검사한 endpoint 목록을 남겨 다음 확인의 기준점으로 사용할 수 있게 했습니다.

<br>

### 로그인 성공 판정

로그인 버튼 클릭 자체를 성공 조건으로 사용하지 않습니다.

클릭 이후에도 비밀번호 오류, 추가 인증, 서버 오류 등의 이유로 로그인 페이지에 남아 있을 수 있기 때문입니다.

판정 순서는 다음과 같습니다.

1. 로그인 실패 메시지 확인
2. 로그인 경로를 정상적으로 벗어났는지 확인

실패 메시지를 먼저 확인하면 단순 timeout으로 처리하지 않고 실제 로그인 실패 원인을 로그에 남길 수 있습니다.

고정 `sleep`은 사용하지 않았습니다. 환경 속도에 따라 너무 짧거나 불필요하게 길어질 수 있기 때문입니다.

페이지 이동은 `wait_for_url`, Network 응답은 `page.on("response")`를 이용해 상태 변화 자체를 기다립니다.

또한 스트리밍 서비스 특성상 이미지, analytics, tracking 요청 등이 지속될 수 있으므로 페이지 대기 조건은 `networkidle` 대신 `domcontentloaded`를 사용했습니다.

<br>

### 실제 확인한 내용

과제 수행 중 실제 DOM과 Network를 확인해 다음 항목을 검증했습니다.

| 항목 | 확인 결과 |
|---|---|
| 로그인 진입 경로 | `/account/login`은 로그인 방식 선택 화면 |
| TVING 로그인 폼 | `/account/login/tving` |
| CJ ONE 로그인 폼 | `/account/login/cj-one` |
| 입력 필드 | `name="id"`, `name="password"` |
| 로그인 버튼 | `<button type="submit">로그인</button>` |
| 마이페이지 | `/my` |
| 인증 gateway | `gw.tving.com/cust/login/v1/web/cjone` |
| 로그인 성공 후 이동 | `/account/profiles` (프로필 선택 화면) |
| `profileNo` 출처 | `api.tving.com/v2/user/info` → `body.profile.profileNo` |

입력 필드에는 `id`나 `data-testid`가 존재하지 않아 현재 DOM에서 상대적으로 안정적인 `name` 속성을 locator로 사용했습니다. `name`은 폼 전송 키로 서버와 연결되어 있어 화면 문구인 `placeholder`보다 변경 가능성이 낮다고 판단했습니다.

접근성 기반 조회는 사용하지 않았습니다. 확인 과정에서 `get_by_label("아이디")`가 같은 화면의 `aria-label="티빙 아이디 회원가입"` 버튼을 부분 매칭으로 선택하는 것을 확인했기 때문입니다. CSS class는 Tailwind 유틸리티와 해시 조합이어서 배포 시 변경될 가능성이 높아 제외했습니다.

또한 로그인 URL에 `returnUrl`을 지정하면 로그인 성공 후 마이페이지로 직접 이동할 수 있는 것을 확인해,

```text
로그인 → 로그인 성공 확인 → 마이페이지 이동
```

대신

```text
로그인 → 마이페이지 redirect
```

흐름으로 단순화했습니다.

<br>

### 로그인 실패 진단 과정

최종적으로 정상 로그인과 `profileNo` 추출까지 확인했으나, 그 전까지 로그인이 반복 실패했습니다. 원인을 좁혀간 과정을 남깁니다. 실패 메시지를 그대로 신뢰하지 않고 구분해서 판정한 사례입니다.

**1. 화면 문구를 원인으로 단정하지 않음**

초기에는 CJ ONE 로그인 화면의 `계정 잠금 안내` 문구를 실패 원인으로 판단했습니다. 그러나 확인 결과 해당 문구는 제출 여부와 무관하게 폼에 **상시 노출되는 정적 안내**였고, 이번 요청에 대한 서버 응답은 별도였습니다.

```text
code: 1031
입력하신 회원정보를 찾을 수 없습니다.
```

화면에 문구가 존재한다는 사실과 그것이 현재 요청의 결과라는 것은 다른 정보이므로, 정적 안내와 제출 결과를 분리해 판정하도록 수정했습니다.

**2. 로그인 유형 불일치 가능성 확인**

서버 메시지가 자격증명 오류와 로그인 유형 불일치를 구분하지 않으므로 유형도 함께 점검했습니다. `tving` 폼으로 제출해도 서비스가 `/account/login/cj-one`으로 라우팅하는 것을 확인해 해당 계정의 유형은 `cj-one`이 맞다고 판단했습니다.

**3. 봇 차단으로 인한 실패와 구분**

다른 계정으로 시도한 구간에서는 인증 gateway 요청이 아예 발생하지 않고 `일시적인 서비스 오류` 문구만 노출됐습니다. 콘솔 확인 결과 원인은 자격증명이 아니었습니다.

```text
pageerror: grecaptcha is not defined
```

reCAPTCHA Enterprise가 초기화되지 않아 로그인 요청 자체가 발생하지 않은 상태였습니다. headed 모드에서도 동일해 단순 headless 감지는 아니었으며, 자격증명 문제와는 구분되는 실패로 분류했습니다.

**4. 최종 확인**

유효한 자격증명 적용 후 로그인과 추출이 정상 동작하는 것을 확인했습니다.

```text
$ uv run extract-profile-no
profile_no: 100000001
```

3회 반복 실행에서 동일한 값을 반환했습니다.

<br>

#### 남은 개선 사항

로그인 제출 후 실패 문구 확인 시점에 고정 대기(`submit_wait_ms`)를 사용하고 있습니다. 응답이 느린 경우 해당 시점에 문구가 아직 렌더링되지 않아 실패 원인이 timeout으로 기록되는 경우를 실제로 확인했습니다.

인증 gateway 응답을 `expect_response`로 대기하거나 문구를 `wait_for(state="visible")`로 대기하도록 변경하면 해소됩니다. 현재는 대기 시간에 의존하는 구간이 한 곳 남아 있습니다.

<br>

### 로그인 요청 URL

로그인 폼 동작을 확인하는 과정에서 자격증명이 GET query string에 포함되는 것을 확인했습니다.

```text
https://www.tving.com/account/login/cj-one?id=...&password=...
```

이 경우 자격증명이 URL 형태로 브라우저 히스토리나 서버 측 요청 로그 등에 기록될 가능성이 있어 credential 노출 관점에서 검토가 필요합니다.

이는 본 자동화 코드에서 생성한 동작이 아니라 실제 로그인 폼 동작이며, 스크립트에서는 해당 URL이나 자격증명을 출력하지 않도록 처리했습니다.
