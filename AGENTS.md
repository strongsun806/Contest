# AGENTS.md — 코드 리뷰 지침

PR마다 실행되는 자동 리뷰 봇(Codex)이 따르는 지침입니다. 보안 검토는 [SECURITY.md](SECURITY.md)를 함께 따릅니다.

## 프로젝트 개요
- 공모전 사이트(위비티·링커리어)를 수집해 IT/Non-IT로 분류하고, VLM으로 요약한 주간 다이제스트를 별도 저장소(`Contest-Subscribe-IT`, `Contest-Subscribe-Non-IT`)에 GitHub Issue로 발행합니다.
- 파이프라인: `collect → dedupe(filters.py) → classify(classify.py) → 트랙별 process(fetch → extract/validate → render) → publish`. 설계는 [SPEC.md](SPEC.md)에 있습니다.
- 상태는 `data/state.json` 한 파일에 저장하고 GitHub Actions(`.github/workflows/digest.yml`)가 job마다 커밋합니다.
- Python 3.12, 테스트는 `pytest`(`tests/`). 네트워크 없이 `tests/fixtures`와 `offline.py`의 `FixtureHttp`로 돌아가야 합니다.

## 리뷰 원칙
- 한국어로 리뷰합니다. 코드 위치는 `파일:줄`로 짚습니다.
- **정확성 버그를 우선**합니다. 스타일·취향 지적은 실제 가독성 문제가 있을 때만, 최대 몇 개로 제한합니다.
- 각 지적에는 "어떤 입력/상태에서 무엇이 잘못되는지" 구체적 시나리오를 붙입니다. 시나리오를 못 대면 지적하지 않거나 질문으로 남깁니다.
- 심각도를 표시합니다: `🔴 반드시 수정` / `🟡 권장` / `💬 질문`.
- 문제가 없으면 짧게 승인 의견만 남깁니다. 칭찬·요약 나열은 하지 않습니다.
- `data/state.json`만 바뀐 `chore(state): …` 봇 커밋/PR은 리뷰하지 않습니다(형식이 깨진 경우만 지적).

## 중점 검토 항목
### 상태(state.json) 호환성
- 운영 중인 `state.json`이 있으므로 필드 추가·이름 변경·의미 변경은 **기존 파일을 그대로 읽어도 동작**해야 합니다(`.get()` 기본값, 마이그레이션 유무 확인).
- 상태 전이(`pending` → `sent`/`skipped`, `moved`, `both`, `sent_in`)가 IT·Non-IT job을 순서대로 돌렸을 때 이중 발송·영구 누락·트랙 왕복 루프를 만들지 않는지 확인합니다.
- `prune` 보존 기간과 dedupe 이력의 관계(지워진 항목이 다시 신규로 잡히는지)를 봅니다.

### 분류·중복 제거
- `filters.py`의 `is_same_contest`/`Fingerprint` 변경은 **오탐(다른 공모전을 같은 것으로 합침)과 미탐 양쪽**을 따집니다. 오탐은 공모전이 조용히 사라지므로 더 심각합니다.
- 규칙 변경에는 실제 사례 기반 회귀 테스트(양성·음성 모두)가 있어야 합니다.
- 분류 기준 변경 시 LLM 프롬프트(`classify.py`, `prompts/extract.md`), Jev 질문, 키워드 규칙(`config.py`)이 서로 모순되지 않는지 확인합니다.

### 외부 호출·실패 처리
- 소스 하나·모델 하나의 실패가 전체 실행을 멈추지 않아야 합니다(기존의 소스별 격리, 2차/키워드 대체 경로 유지).
- 상세 수집 실패 건은 `pending`으로 남아 재시도되어야 하며 `skipped`로 버려지면 안 됩니다.
- 새 HTTP 요청은 `HttpClient`(호스트별 지연·재시도·timeout)를 거치는지, LLM 호출에 비용 상한(`MAX_ITEMS`, `MAX_POSTERS`, 배치 크기)이 적용되는지 확인합니다.

### 발행
- Issue는 되돌리기 어려운 외부 출력입니다. dry-run(`DRY_RUN`, `--dry-run`)에서 Issue 생성·상태 커밋이 절대 일어나지 않는지 확인합니다.
- 발행 실패 시 상태가 `sent`로 기록되어 다음 주에 누락되지 않는지 봅니다.
- 렌더링(`render.py`)은 외부 텍스트를 마크다운에 넣으므로 이스케이프(`|`, `[`, `~` 등)와 링크 URL 검증을 확인합니다.

### 워크플로
- `digest.yml` 변경은 job 순서(classify → publish-it → publish-non-it), artifact로 넘기는 상태, `concurrency`, cron 시간, 수동 발행 주 cron 건너뛰기 로직이 유지되는지 봅니다.
- 권한(`permissions`)은 최소로 유지되어야 합니다. 세부는 SECURITY.md를 따릅니다.

### 테스트·문서
- 동작 변경에는 테스트가 따라와야 합니다. 테스트가 네트워크·API 키를 요구하면 지적합니다.
- 환경변수·설정 추가 시 `config.py`, `.env.example`, `README.md` 변수 표, 워크플로 `env`가 함께 갱신됐는지 확인합니다.
- SPEC.md의 설명과 실제 동작이 어긋나면 지적합니다.

## 코드 스타일 (참고)
- 주석·docstring·로그는 한국어. "왜"를 설명하는 주석만 남기고 코드를 반복하는 주석은 지양합니다.
- 광범위한 `except Exception`은 대체 경로가 있고 `# noqa: BLE001 - 사유`가 붙은 경우만 허용합니다.
- 새 의존성 추가는 필요성을 확인합니다(`pyproject.toml`, `uv.lock` 동시 갱신).
