# SECURITY.md — 보안 검토 지침

자동 리뷰 봇과 리뷰어가 PR을 볼 때 따르는 보안 기준입니다. 일반 리뷰 지침은 [AGENTS.md](AGENTS.md)에 있습니다.

## 위협 모델
| 자산 | 위치 | 노출 시 영향 |
|---|---|---|
| `ISSUE_TOKEN` (PAT/App 토큰) | Actions secret | 발행 저장소 Issue 작성·잠금, 상호작용 제한(Administration) 조작 |
| `OPENROUTER_API_KEY` | Actions secret | 과금 남용 |
| 이 저장소 쓰기 권한 | 워크플로 `contents: write` | 코드·상태 변조, 악성 워크플로 실행 |
| 발행 Issue 본문 | 구독자에게 알림 발송 | 피싱 링크·악성 콘텐츠 유포 |

신뢰하지 않는 입력: **공모전 사이트 HTML·포스터 이미지, LLM/VLM 응답, 외부 PR의 코드**. 이들은 모두 공격자가 조작할 수 있다고 가정합니다.

## 검토 항목
### 1. 비밀값
- 토큰·API 키·`.env`가 커밋되지 않는지 (테스트 fixture, 로그 출력, 예시 파일 포함).
- 비밀값이 로그·예외 메시지·Issue 본문·artifact(`state.json`, `manual-published.txt`)에 들어가지 않는지.
- 비밀값을 원래 대상(GitHub API, OpenRouter) 외의 호스트로 보내는 코드가 없는지. `Authorization` 헤더가 붙은 요청의 URL이 설정/입력으로 바뀔 수 있으면 지적합니다.

### 2. GitHub Actions
- `pull_request_target`, `workflow_run`에서 PR 코드를 checkout·실행하는 패턴 금지. 외부 PR에 secret이 노출되지 않아야 합니다.
- `${{ github.event.* }}`, `inputs.*` 등을 `run:` 스크립트에 직접 보간하지 말고 `env:`로 넘겼는지 (스크립트 주입).
- `permissions`는 job별 최소 권한. 새 권한(`issues`, `pull-requests`, `id-token` 등) 추가는 사유가 있어야 합니다.
- 서드파티 액션은 신뢰할 수 있는 게시자이거나 커밋 SHA로 고정되어 있는지. 새 액션 추가는 반드시 지적 대상입니다.
- 상태 커밋 job이 `state.json` 외의 파일을 `git add` 하지 않는지.

### 3. 외부 콘텐츠 처리
- **프롬프트 인젝션:** 공모전 본문·포스터에 "이전 지시를 무시하라" 같은 문구가 있어도 결과가 스키마(`models.py` pydantic, JSON schema)와 `validate.py` 검증으로 제한되는지. LLM 출력이 코드 실행·파일 경로·URL 요청 대상·셸 명령으로 이어지는 경로가 없어야 합니다.
- **Issue 본문 오염:** LLM이 만든 텍스트와 링크는 마크다운 이스케이프를 거치고, 링크는 원문·포스터 출처 도메인(위비티·링커리어 등)으로 제한되는지. `@멘션`, `#번호` 자동 링크, HTML 태그, 이미지 트래킹 URL이 그대로 들어가지 않는지.
- **SSRF·과도한 요청:** 상세·포스터 URL을 페이지에서 추출해 요청할 때 `http(s)`만 허용하고, 사설 IP·메타데이터 주소로 갈 수 없는지. 응답 크기·이미지 크기(`image_max_side`), 페이지 수(`MAX_PAGES`), 요청 지연(`REQUEST_DELAY`) 상한이 유지되는지.
- **파싱:** HTML·이미지 파싱 라이브러리에 신뢰할 수 없는 입력을 넣을 때 `eval`, `pickle`, `yaml.load`(unsafe), `subprocess`(shell=True) 같은 위험 API를 쓰지 않는지.

### 4. 의존성
- 새 패키지는 잘 알려진 것인지, 이름 오타(typosquatting)가 아닌지, `uv.lock`이 함께 갱신됐는지.
- 버전 범위를 크게 풀거나 lock 없이 설치하는 변경은 지적합니다.

### 5. 크롤링 윤리·정책
- 대상 사이트의 robots.txt·이용약관을 우회하는 변경(지연 제거, User-Agent 위장, 로그인 우회, 캡차 회피)은 지적합니다.
- 개인정보(담당자 연락처 등)를 Issue에 불필요하게 옮기지 않는지.

## 심각도 기준
- `🔴 반드시 수정`: 비밀값 노출 가능성, 외부 PR에서의 secret 접근, 스크립트 주입, 임의 URL로의 인증 요청, LLM 출력의 코드/명령 실행.
- `🟡 권장`: 권한 과다, 액션 버전 미고정, 이스케이프 누락, 요청 상한 완화.
- 보안 지적에는 공격 시나리오(누가, 어떤 입력으로, 무엇을 얻는지)를 붙입니다. 실제 동작하는 익스플로잇 코드는 PR 코멘트에 쓰지 않습니다.

## 취약점 신고
공개 Issue·PR 코멘트 대신 GitHub의 **Private vulnerability reporting**(Security 탭 → Report a vulnerability)으로 저장소 관리자에게 알려 주세요.
