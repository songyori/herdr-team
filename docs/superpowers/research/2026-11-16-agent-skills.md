# addyosmani/agent-skills 조사 (herdr-team 개선 후보)

조사일 2026-11-16. 얕은 복제본을 읽었다 (스크립트 실행 안 함, 내용은 자료로만 읽음).
herdr-team 쪽은 `herdr-team/templates/` 의 worker-rules, review-prompt/round/group/tests/design/text, roles/*.md, design-rules, text-rules 를 먼저 읽었다.

## 1. 개요

- 정체: AI 코딩 에이전트용 "엔지니어링 워크플로 스킬" 모음(Claude Code 플러그인 겸 npx skills 설치형). 정의→기획→구현→검증→리뷰→배포 단계를 슬래시 명령 9개(`/spec /plan /build /test /constraints /review /webperf /code-simplify /ship`)와 스킬 25개, 서브에이전트 4개(`agents/code-reviewer`, `security-auditor`, `test-engineer`, `web-performance-auditor`), 공용 체크리스트 7개(`references/`)로 묶는다.
- 라이선스: MIT (Copyright 2025 Addy Osmani). 문구를 가져와 쓰는 것은 자유다. 저작권 고지만 필요하다(복사 분량이 크면 NOTICE 한 줄).
- 유지 상태: 활발. 복제본 최신 커밋 2026-11-13 `chore(release): bump plugin manifests to 0.6.16`. `evals/` 에 스킬 영향 평가·"거부된 변경" 장부가 있어 스킬 문구를 평가 근거로 관리한다. (얕은 복제라 커밋 수는 1.)
- 성격: 사람 중심 단일 에이전트 세션을 가정한다. 워커 격리·소유 경로·다중 모델 오케스트레이션은 없다. 따라서 "워크플로 골격"은 herdr-team 이 이미 더 강하고, 가져올 가치는 "검사 항목의 구체성"에 있다.

### 스킬 목록 (한 줄씩)

| 스킬 | 한 줄 |
|---|---|
| using-agent-skills | 어느 스킬을 언제 쓸지 정하는 메타 스킬 |
| idea-refine | 모호한 아이디어를 발산·수렴으로 구체화 |
| interview-me | 질문 하나씩, 추측을 붙여 묻고 신뢰도 ~95% 에서 멈추는 요구 인터뷰 |
| spec-driven-development | 코드 전에 spec(목표·명령·구조·스타일·테스트 전략·경계 3단·성공 기준·범위 밖·미해결) |
| planning-and-task-breakdown | 의존 그래프, 수직 슬라이스, 태스크 크기 표(XS–XL), 체크포인트 |
| incremental-implementation | 얇은 조각 단위 구현, 범위 규율(Rule 0.5), 증분 체크리스트 |
| test-driven-development | RED-GREEN-REFACTOR, Prove-It(버그는 재현 테스트 먼저), 테스트 피라미드·크기, DAMP |
| constraint-driven-development | 프로젝트 품질 기준을 숫자·명령으로 `CONSTRAINTS.md` 에 쓰고 에이전트가 기준을 낮추는 것을 막음 |
| doubt-driven-development | 판단마다 새 맥락의 적대적 리뷰어(다른 모델 포함)에 반박시키고 3회 안에 끝냄 |
| code-review-and-quality | 5축 리뷰(정확성·가독성·구조·보안·성능), 심각도 표시, 변경 크기, 리뷰 과정 |
| code-simplification | 동작 불변 단순화 |
| debugging-and-error-recovery | 근본 원인 디버깅 |
| frontend-ui-engineering | 컴포넌트·상태·디자인 시스템 준수·AI 미학 회피·접근성·반응형 |
| browser-testing-with-devtools | Chrome DevTools MCP 로 실제 브라우저 검증 |
| api-and-interface-design | 모듈 경계·계약 설계 |
| security-and-hardening | 위협 모델, 입력 검증, 인증·인가, 의존성, 파괴적 경로 작업 |
| performance-optimization | 측정→병목→수정→재측정, Core Web Vitals, 쿼리 |
| observability-and-instrumentation | 로그·지표·추적·알림 |
| ci-cd-and-automation | 파이프라인 품질 관문 |
| git-workflow-and-versioning | 원자적 커밋·브랜치·충돌 |
| documentation-and-adrs | ADR, 문서-코드 드리프트 탐지 |
| deprecation-and-migration | 폐기·이전 |
| shipping-and-launch | 배포 전 체크리스트·롤백 |
| context-engineering | 에이전트 컨텍스트 구성 |
| source-driven-development | 공식 문서에 근거해 구현 |

공용 `references/`: definition-of-done, testing-patterns, accessibility-checklist, performance-checklist, security-checklist, observability-checklist, orchestration-patterns.

## 2. herdr-team 에 넣을 만한 항목

표기: [그대로] 거의 그대로 / [변형] 우리 구조에 맞게 고침 / [참고] 참고만. "이미 있음"은 중복이라 넣지 않는다.
영향 큰 순서로 적었다. 맨 앞 B1–B4 가 "산출물이 실제로 더 좋아지는" 쪽이다.

### (c) 코드 품질·검증 — 우선순위 높음

**B1. 테스트 약화·검사 우회 금지와 diff 점검 (constraint-driven 의 "floor"와 "Guard the bar")** [변형]
- 출처: `skills/constraint-driven-development/SKILL.md` Step 3 "Floor", Step 6 "Guard the bar itself".
- 내용: 새 억제 주석(`@ts-ignore`, `eslint-disable`, `# noqa`, `# type: ignore`, `istanbul ignore`), `.skip`/삭제된 테스트, 빈 `catch {}`, "Not implemented" 스텁, 임계값 하향, 새 예외 행을 diff 에서 찾는다. "에이전트는 꾀를 부리지 않고 빨간 검사를 가장 싼 길로 초록으로 만든다"는 관찰에 근거한다.
- 현황: herdr-team 에는 이 규칙이 없다(templates 전체에서 `skip`·`ts-ignore`·`eslint-disable` 0건). tester.md 에 "테스트를 약하게 만들거나 건너뛰거나 지우지 않는다" 한 줄만 있고 developer 와 리뷰어에는 없다. `lib/hteam/lint.py`·`review.py` 의 자동 검사에도 해당 항목이 없다.
- 반영 위치:
  - `templates/worker-rules.md`: 번호 항목 추가(모든 직무 공통) "검사를 통과시키려고 억제 주석·`.skip`·테스트 삭제·단언 제거·빈 catch 를 더하지 않는다. 꼭 필요하면 보고서에 이유를 적고 ask 로 묻는다."
  - `templates/review-prompt.md` 기준 3번 아래 또는 P1 정의: "이 태스크가 새로 더한 억제 주석·`.skip`·삭제된 테스트·약해진 단언은 이유가 보고서에 있고 타당하지 않으면 P1".
  - `lib/hteam/lint.py`(자동 검사, 의심 위치로 리뷰 프롬프트에 주입): diff 의 추가 줄에서 위 패턴을 grep 해 `{{lint}}` 처럼 주입. 언어는 설정이 모르므로 패턴 목록은 고정 소수만(JS/TS/Python/Go/Rust `#[ignore]`).
  - `roles/tester.md` 하지 않는 것에 이미 있는 문장은 유지하고 "단언을 줄이는 것도 같다"를 보탠다.

**B2. 버그 수정은 재현 테스트가 먼저 실패해야 한다 (Prove-It)** [그대로]
- 출처: `skills/test-driven-development/SKILL.md` "The Prove-It Pattern", `agents/test-engineer.md` §3.
- 내용: 수정 전에 버그를 재현하는 테스트를 쓰고 실패를 확인한 뒤 고쳐서 통과시킨다. "고친 뒤 새로 쓴 테스트가 고치기 전 코드에서도 통과하면 아무것도 증명하지 못한다."
- 현황: 없음. herdr-team 은 리뷰 지적·회귀 수정 태스크(`## 회귀` → 회귀 수정 태스크)로 버그 수정을 많이 만드는데, 수정 워커에게 재현 테스트 의무가 없다. 리뷰어도 "수정이 맞는지" 를 눈으로만 판단한다.
- 반영 위치:
  - `roles/developer.md` 품질 기준: "회귀 수정·버그 수정 태스크(사양 title/change 에 수정이 드러남)는 먼저 실패하는 재현 테스트를 owns 안에 쓰고, 실패 출력 원문과 수정 뒤 통과 출력 원문을 둘 다 보고서에 붙인다."
  - `review-prompt.md` 기준 1 뒤: "수정 라운드·회귀 수정이면 재현 테스트가 수정 전 커밋에서 실패하는지 `git stash` 없이 확인한다(읽기 전용 규칙 때문에 직접 되돌리지 말고 보고서의 실패 출력 원문과 대조)". 읽기 전용 정책과 충돌하므로 리뷰어는 보고서 증거 대조까지만 하게 한다(아래 §3).
  - 회귀 수정 태스크를 만드는 코드(`lib/hteam/followups.py` 추정)의 사양 템플릿 constraints 에 위 한 줄.

**B3. 리뷰어의 변이 실험으로 "이 테스트가 정말 잡는가" 확인 [변형, 주의]**
- 출처: `skills/code-review-and-quality/SKILL.md` Step 2 끝: 변경이 더한 조건 하나를 뒤집어(부정 제거, `&&`→`||`) 테스트를 돌리고, 초록이면 어떤 테스트가 구멍인지 지적한 뒤 파일을 복원.
- 현황: 없음. review-prompt 는 "테스트·빌드 실행" 은 허용하지만 "추적 파일을 바꾸면 판정 무효"다.
- 충돌: 추적 파일을 바꾸는 실험은 현재 정책(실행 정책 4번째 항목)과 직접 부딪친다. 같은 작업 폴더에서 다른 워커가 동시에 일하므로 임시 수정이 남의 시험에 새어 들어갈 위험도 있다.
- 채택안: 기본은 [참고]. 도입한다면 `review-tests.md`(묶음 테스트 리뷰) 한정으로 "임시 복사본(`mktemp -d` 에 `git worktree` 가 아닌 파일 복사)에서만 변이 1건, 원본 경로 수정 금지"를 허용하는 별도 단계로 한다. 효과(약한 테스트 적발)는 크지만 격리 설계가 먼저다.

**B4. 변경 범위 규율: "봤지만 건드리지 않은 것" 보고 (Rule 0.5)** [변형]
- 출처: `skills/incremental-implementation/SKILL.md` Rule 0.5, 포맷 `NOTICED BUT NOT TOUCHING:`.
- 내용: 범위 밖 개선점은 고치지 않고 목록으로 남긴다. 리뷰어는 "관련 없는 정리·리팩터링·기능 추가"를 지적한다.
- 현황: developer.md 에 "관련 없는 리팩터링을 하지 않는다" 한 줄, owns 경계 규칙만 있다. 발견한 문제를 어디에 적는지는 없다(그냥 사라지거나 몰래 고쳐진다).
- 반영 위치: `worker-rules.md` 3번(보고서 절)에 `### 건드리지 않고 본 것` 소절 추가(없으면 "없음"). `lib/hteam/followups.py` 가 후속 태스크 후보로 읽을 수 있으면 그대로 연결. `review-prompt.md` 기준 3번에 "diff 가 태스크 범위를 넘는 변경(무관한 이름 바꾸기, 주석 삭제)" 추가.

### (a) 프로젝트 프로세스

**A1. 태스크 크기 기준과 "and" 휴리스틱** [변형]
- 출처: `skills/planning-and-task-breakdown/SKILL.md` "Task Sizing Guidelines": 파일 수 XS(1)/S(1–2)/M(3–5)/L(5–8)/XL(8+ 쪼갠다), 쪼갤 신호 4개(한 세션 2시간 초과, 수용 기준을 3개 이하로 못 적음, 독립 하위 시스템 둘 이상, 제목에 "그리고").
- 현황: planner.md 는 묶음 3–6개와 owns 겹침 검사만 말하고 개별 태스크 크기 기준이 없다. `plan check` 도 크기를 보지 않는다.
- 반영 위치: `roles/planner.md` tasks.toml 형식 절에 "developer 태스크는 owns 가 대략 5개 파일을 넘거나 acceptance 가 5개를 넘거나 title 에 '및·그리고' 가 있으면 둘로 나눈다(문서·에셋 전용 제외)". `lib/hteam/plan.py` 에 경고 수준 검사(acceptance 개수, title 접속어)를 더하면 `plan check` 에서 바로 보인다. 숫자는 우리 데이터(과거 태스크의 리뷰 라운드 수)로 보정 필요.

**A2. 체크포인트: 묶음 중간 통합 확인** [참고]
- 출처: 같은 스킬 Step 5 "매 2–3 태스크 뒤 체크포인트(테스트·빌드·핵심 흐름)". 위험이 큰 태스크를 앞에 둔다.
- 현황: herdr-team 은 묶음 끝의 tester 태스크가 그 역할. 묶음이 3–6개라 이미 대응. "위험 큰 것 먼저" 한 줄만 planner.md 에 보탤 만하다 [변형]: depends_on 이 허용하는 범위에서 외부 연동·데이터 모델·인증 같은 불확실한 태스크를 앞 묶음으로.

**A3. spec 에 실행 명령·경계 3단(Always/Ask first/Never)과 미해결 질문** [변형]
- 출처: `skills/spec-driven-development/SKILL.md` Phase 1 spec 템플릿: Commands(플래그까지 완전한 실행 명령), Project Structure, Code Style(실제 코드 조각 하나), Testing Strategy, Boundaries(Always/Ask first/Never), Out of Scope(왜 미뤘는지 한 줄), Open Questions.
- 현황: spec.md 항목에 "기술 스택과 실행 환경"·"범위 밖"·"자동 결정"은 있다(이미 있음). 없는 것: (1) 빌드·테스트·린트·개발 서버의 정확한 명령(워커가 매번 추측하거나 보고서마다 달라짐; `[test]` 는 테스트 명령만), (2) 경계 3단, (3) 코드 스타일 예시 한 조각.
- 반영 위치: `roles/planner.md` 산출물 spec.md 항목에 "실행 명령(설치·빌드·린트·테스트·개발 서버)과 경계(항상/먼저 물을 것/절대 안 함)"를 넣고 체크리스트 9번(기술 스택과 실행 환경)의 결정 항목에 명령까지 포함. 경계의 "먼저 물을 것"은 worker-rules 의 ask 규칙과 같은 어휘라 자연스럽다. developer 입력에 spec.md 의 해당 절을 명시(`roles/developer.md` 입력).

**A4. 후속 변경은 delta spec (증분 기획)** [참고]
- 출처: spec-driven "Follow-up changes get a delta spec"(현재 동작·새 동작·성공 기준·경계).
- 현황: planner.md 가 이미 증분 기획(추가 요청만 묻기, 적용한 task 불변)을 갖고 있다. delta 절의 "현재 동작 / 새 동작" 구분만 spec.md 증분 기록 형식에 참고할 만하다. 기능 추가 없음.

**A5. 인터뷰: 질문마다 추측을 붙이고 "원하는 것 vs 해야 한다고 생각하는 것" 구분** [참고]
- 출처: `skills/interview-me/SKILL.md` Step 2–4(질문 하나, 추측 첨부, 사용자 말로 재진술, 명시적 예 확인, 95% 신뢰 정지).
- 현황: 이미 비슷하다(한 질문씩, 추천안·사유, 확정 질문, 13항목 체크리스트). 오히려 우리 쪽이 구조화돼 있다. 새로 가져올 것은 "재진술 후 확인" 정도인데 확정 질문의 `context`(계획 핵심)가 그 역할을 한다. 넣지 않는다.

**A6. Definition of Done: 수용 기준(태스크별)과 별개의 고정 완료 기준** [변형]
- 출처: `references/definition-of-done.md` (정확성·품질·통합·문서·출시 준비 체크리스트, "AC 는 태스크별, DoD 는 항상 같다").
- 현황: 완료 기준이 role 문서의 "품질 기준"에 흩어져 있다. developer 는 AC 실행 + 테스트, 리뷰는 별도. 항상 같은 바닥 기준을 한 곳에 두고 worker-rules 가 참조하게 하면 보고서 `## rN` 절에 "DoD 점검" 한 줄 표(해당 없음 허용)를 요구할 수 있다.
- 채택안: 전체 이식 말고 항목 다섯으로 줄여 `worker-rules.md` 에: (1) 런타임에서 실제로 실행해 확인(타입·빌드 통과만으로 완료 아님), (2) 새 동작을 덮는 테스트가 수정 전에는 실패, (3) 기존 테스트 통과, (4) 디버그 출력·주석 처리된 코드·죽은 코드 없음, (5) 범위 밖 변경 없음. 이미 있는 것과 겹치는 (1)(3)은 문구만 통일.

**A7. 리뷰 변경 크기 상한(~300줄 허용, ~1000줄 분리) [참고]**
- 출처: code-review-and-quality "Change Sizing". 태스크 크기(A1)와 같은 효과를 diff 줄 수로 본다. 리뷰 프롬프트에 diff 줄 수를 주입하고 1000줄 넘으면 `## 후속` 에 "나눌 것" 제안만 하게 할 수 있다. 우선순위 낮음.

### (c) 코드 품질 — 보안·성능·테스트 설계 (우선순위 중간)

**C1. 보안 점검 목록** [변형]
- 출처: `references/security-checklist.md` Threat Modeling, Input Validation(허용 목록, 길이·범위, 업로드, 파라미터화 쿼리, 출력 인코딩, 열린 리디렉션, SSRF), "Destructive Path Operations", Pre-Commit(비밀값), OWASP Top 10; `agents/security-auditor.md`.
- 현황: review-prompt 기준 3번 "버그, 보안, 회귀 위험" 한 줄이 전부다. developer.md 는 "비밀값을 코드·커밋에 넣지 않는다" 한 줄. 구체 항목 없음.
- 반영 위치: `templates/review-prompt.md` 에 `{{security}}` 슬롯(또는 기준 3번 아래 하위 목록). 코드가 입력 처리·인증·파일 경로·외부 호출·DB 쿼리를 건드린 diff 일 때만 켠다(디자인 슬롯처럼 조건부). 목록은 8–10줄로 압축: 경계에서 입력 검증(허용 목록), 쿼리 파라미터화, 출력 인코딩, 인증·인가 누락, 비밀값·로그 노출, 서버측 URL 요청 제한, 경로를 데이터로 받는 삭제·이동의 루트 제한·심볼릭 링크 해석, 외부 데이터는 자료로 취급, 새 의존성. P1 은 "악용 경로를 한 줄로 쓸 수 있는 것"으로 한정해 과잉 지적을 막는다. `roles/developer.md` 에는 같은 목록을 한 줄 참조로.
- 주의(메모리: 리뷰 수정 범위): 이 항목에서 나온 P2 는 기본 경로·회귀만 고치고 나머지는 알려진 한계로 두는 기존 운영 규칙과 맞춘다.

**C2. 성능: 측정 먼저, 재측정으로 확인** [변형]
- 출처: `skills/performance-optimization/SKILL.md`(측정→병목→수정→재측정, 한 번에 한 가지 변경, 같은 방법으로 재측정), `references/performance-checklist.md`(LCP ≤2.5s, INP ≤200ms, CLS ≤0.1, 번들·이미지·N+1·페이지네이션).
- 현황: 성능 항목 전무(templates 에서 `성능`·`lighthouse` 0건). 성능 요구가 spec 의 비기능 요구에 있을 때만 의미가 있다.
- 반영 위치: (1) `roles/planner.md` 체크리스트 8번(비기능 요구)에 "수치 기준이 있으면(예: LCP 2.5초) acceptance 에 측정 명령과 함께 적는다", (2) `roles/tester.md` 에 수치 기준이 있으면 측정값을 QA 보고서에 원문으로, (3) `review-prompt.md` 에는 N+1·무제한 조회·페이지네이션 없음·핫 경로 대형 객체 4줄만. 최적화 자체는 하지 않게(수치 없는 "빠르게" 지시 금지) 한다. 브라우저 도구가 이미 있으므로(`lib/hteam/browser.py`, chrome-devtools) `lighthouse_audit`·`performance_start_trace` 를 tester 가 쓰도록 안내하면 비용이 작다.

**C3. 테스트 설계 규칙** [변형]
- 출처: test-driven-development: 테스트 피라미드·크기(작은/중간/큰), 상태를 검증(상호작용 아님), DAMP, 실물 > 가짜 > 스텁 > 목, 경계에서만 목, 테스트당 개념 하나, 서술적 이름, 안티패턴 표(구현 세부 테스트, 불안정 테스트, 스냅샷 남용, 격리 없음, 모든 것을 목). `agents/test-engineer.md` 시나리오 표(정상·빈 입력·경계값·오류 경로·동시성).
- 현황: tester.md 는 "수용 기준마다 테스트 하나 이상"과 실패 재현만 말한다. 테스트의 품질(너무 목을 쓴다, 구현 세부를 고정한다)을 보는 기준이 없다. `review-tests.md` 는 3줄.
- 반영 위치: `templates/review-tests.md` 확장(10줄 이내): "목으로 제품 코드를 대체해 통과하는 테스트인가, 구현 세부(비공개 함수·호출 순서)를 단언하는가, 빈 입력·경계·오류 경로가 있는가, 서로 순서에 의존하는가". `roles/tester.md` 품질 기준에 시나리오 표(정상·빈·경계·오류·동시성)를 수용 기준별로 최소 하나씩 확인. 목록은 짧게 유지한다.

**C4. 5축 리뷰의 구조 항목: 조건 덧붙이기·중복 조건문·추상화 정당성** [변형]
- 출처: code-review-and-quality "가독성·구조" 의 굵은 질문들(새 조건문이 무관한 흐름에 붙었나, 같은 모양의 반복 조건문=빠진 모델, 경계 밖 기능 로직 누출, 정리가 복잡도를 줄이나 옮기기만 하나, 불필요한 any/캐스트) 와 "Structural Remedies" 목록(지적할 때 구체적 재구조화 동작 제시), "Dead Code Hygiene"(모르는 것은 지우지 말고 묻는다).
- 현황: review-prompt 의 기준은 4개뿐이고 코드 구조는 P2·P3(후속)에 묶여 있다. 가독성·구조 지적의 품질이 리뷰어 재량이다.
- 반영 위치: `review-prompt.md` 기준 3번 아래 "구조(P2 이하, 새로 만든 것만)" 소절 4–5줄. P1 으로 올리지 않는다(막지 않는 원칙 유지). "고칠 방향" 필드에 이름 붙은 재구조화 동작(조건문 묶음→디스패처, 중복 분기 합치기, 통과만 하는 래퍼 삭제)을 쓰게 하는 한 줄은 디자인 7번(고칠 방향의 순서)과 같은 모양이라 넣기 쉽다.

**C5. 심각도 라벨 정렬(Nit/Optional/FYI)과 "근거 확인 후 지적"** [참고]
- 출처: code-review Step 4: 호출처·가드·테스트를 확인해 반증되면 버린다, 기존 결함과 이 변경이 만든 회귀를 구분 표기, 높은 확신 소수의 지적이 낫다.
- 현황: herdr-team 은 이미 P1/P2/P3, `(새로 생김)/(회귀)/(기존)`, 지적 15개 상한, "확인 못 하면 지적하지 않는다"를 갖고 있다(이미 있음, 더 정교함). 넣지 않는다.

**C6. 제약을 숫자·명령으로 적고 래칫으로 후퇴 금지** [변형, 선택]
- 출처: `skills/constraint-driven-development/SKILL.md` Step 3·7: "측정하되 아직 강제하지 않음" 표(오늘 값, 방향: 떨어지면 안 됨), 변경된 줄 커버리지 ≥80% 같은 기본값과 "근거 없는 수치는 지워진다" 원칙, "외부 검사(axe-core, osv-scanner, Lighthouse)가 하나는 있어야 순환이 아니다".
- 현황: `[test]` 는 quick/full 두 명령뿐이고 커버리지·린트·타입·접근성 자동 검사를 기획 단계에서 정하는 자리가 없다. 자동 검사(`hteam review` 의 lint/textlint/designdiff)는 휴리스틱 의심 위치다.
- 반영 위치(선택): `tasks.toml` 의 `[test]` 에 선택 키 `lint`, `typecheck` 를 더해 testgate 가 리뷰 전에 돌린다. 이득은 있으나 testgate·확정 질문 `--test-confirm` 스키마·보안 경고까지 바꾸는 변경이라 범위가 크다. 먼저 planner.md 에서 인터뷰 9번(기술 스택·실행 환경) 결정에 "린트·타입체크 명령 유무"를 묻는 것까지만 하고, 스키마 확장은 사용자 결정으로 미룬다.

### (b) 디자인 품질

herdr-team 의 design-rules(§1 금지 목록·§2 접근성 14항·§3–§7)와 review-design(금지 항목 즉시 P1, 지운 줄 읽기, 빠진 상태, 대비 계산)이 agent-skills 의 `frontend-ui-engineering`·`accessibility-checklist` 보다 훨씬 구체적이다. 거의 모든 항목이 이미 있다(AI 미학 표 ↔ design-rules §1, WCAG 체크 ↔ §2, 빈·오류 상태 ↔ §7, 반응형 ↔ §5).

가져올 것이 있다면 두 가지뿐이다.
- D1. 레퍼런스 근거를 "화면의 일·주요 동작·필요한 상태·반응형 규칙·거부할 패턴"의 짧은 디자인 계약으로 쓰고 구현 전에 확정 [참고]. 출처 frontend-ui-engineering "Reference-led UI quality". 현황: director.md 단계 ① 레퍼런스·notes.md `## 확정 값`이 이미 같은 역할이다. 추가 없음.
- D2. 자리표시 문구로 레이아웃 문제가 가려진다(lorem ipsum 금지, 실제 길이의 내용으로) [변형]. 출처: 같은 절 AI 미학 표의 "Lorem ipsum-style copy". 현황: design-rules 에 실제 길이 데이터로 확인하라는 항목은 `상태`(§7)에서 간접적. `roles/designer.md` "확인한 화면"에 "긴 문구·긴 이름·0건·많은 건수로 한 번씩 본다" 한 줄이면 된다(한글 줄바꿈 `keep-all` 점검과 짝). 소규모 개선.

접근성 체크리스트 중 우리에게 없는 것: "건너뛰기 링크가 키보드 포커스에서 보임"은 §2 13번에 이미 있고, "필수 입력을 색만으로 표시하지 않음", "표의 `<th scope>`"는 §2 에 없다. `design-rules.md` §2 에 한 줄씩(표 머리글·필수 표시) 추가 후보, 영향은 작다.

## 3. herdr-team 현재 규칙과의 충돌

| 항목 | agent-skills 쪽 | herdr-team 쪽 | 처리 |
|---|---|---|---|
| 리뷰어의 파일 수정(변이 실험, B3) | 코드를 임시로 뒤집어 돌리고 복원 | 리뷰어는 REVIEW_FILE 외 쓰기 금지, 추적 파일을 바꾸면 판정 무효, 작업 폴더를 다른 워커와 공유 | 그대로는 불가. 임시 복사본에서만이라는 별도 설계가 필요하고 기본은 보류 |
| Prove-It 의 "수정 전 커밋에서 실패 확인"(B2) | 테스트를 고치기 전 코드에서 실행 | git stash·checkout 금지(worker-rules 1), 리뷰어 git 쓰기 금지 | 워커는 보고서에 실패 출력 원문을 붙이게 하고 리뷰어는 그 원문과 대조만 한다(되돌려 실행하지 않는다) |
| 사람이 중간에 승인하는 체크포인트 | 매 2–3 태스크마다 사람 검토 | 자동 진행, 사용자 승인은 기획 확정·디자인 일괄 승인에만 | 도입하지 않는다. 묶음 tester 태스크가 대체 |
| "리뷰는 빠르게(하루 안)"·사람 리뷰 응대 | 사람 중심 PR 흐름 | Codex 교차 리뷰, 라운드 기반 | 해당 없음(참고도 불필요) |
| "나중에 정리하겠다" 거부 | 정리 후 병합 요구 | P2·P3 는 막지 않고 후속으로 둔다(메모리: 엣지 케이스 P2 는 알려진 한계) | 충돌. herdr-team 의 비차단 원칙을 유지하고 가져오지 않는다 |
| CONSTRAINTS.md 를 저장소 루트의 단일 소스로 | 사람이 인터뷰해 수치 확정 | 기획 확정 질문과 `[test]` 확정 식별값 흐름 | C6 은 이 흐름에 맞춰 `tasks.toml` 에 넣어야 하고 루트에 새 파일을 두지 않는다 |
| TDD 전면 강제 | 모든 로직에 RED 먼저 | 직무 분리: developer 단위 테스트(owns 안), tester 통합 테스트(`tests/`) | 도입하지 않는다. B2 만 버그 수정에 한정해 채택 |
| 한 파일 1000줄 초과 신호, 태스크당 파일 5개 | 크기 제한 | owns glob 으로 범위를 정한다 | A1 은 경고로만 |
| 질문 도구 사용 | 사용자에게 바로 질문 | AskUserQuestion 금지, `hteam ask-user` 경유 | 인터뷰 스킬을 그대로 쓸 수 없음. 어차피 A5 는 채택 안 함 |
| 영어 원문 | 한국어 문체 규칙 없음 | text-rules, voice.md | 문구는 우리 한국어 규칙으로 다시 쓴다 |

## 4. 권장 채택 순서

1. B1(테스트·검사 약화 금지 + 자동 검사 패턴) — 현재 방어선이 tester.md 한 줄뿐이라 가장 큰 구멍. lint.py 연동은 작은 변경.
2. B2(버그 수정은 재현 테스트와 실패 출력 원문) — 회귀 수정 태스크 사양에 문장 하나.
3. B4(건드리지 않고 본 것 소절) + A6 의 DoD 5줄 — worker-rules 한 곳에서 해결.
4. A1(태스크 크기 경고)·A3(spec 의 실행 명령과 경계) — planner.md 와 `plan check`.
5. C1(보안 조건부 슬롯)·C3(review-tests 확장)·C2(수치 있는 성능만).
6. C6, B3 은 설계가 필요하니 보류하고 사용자 결정을 받는다.

이식할 때 영어 문구를 복사하지 말고 한국어 지침으로 다시 쓴다. MIT 라 문구 이식도 허용되지만 출처 주석(`<!-- 출처: addyosmani/agent-skills, MIT -->`) 한 줄이면 충분하다.
