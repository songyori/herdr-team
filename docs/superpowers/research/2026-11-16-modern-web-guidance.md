# GoogleChrome/modern-web-guidance-src 조사

조사일 2026-11-16. 얕은 clone 을 읽었다. 내려받은 스크립트는 실행하지 않았다.
출처 표기: `S:` = `https://github.com/GoogleChrome/modern-web-guidance-src/blob/main/` 아래 경로.

## 1. 이 저장소가 무엇인가

| 항목 | 내용 |
|---|---|
| 성격 | 코딩 에이전트에게 "최신 웹 플랫폼 방식"을 먹이는 가이드 모음의 **원본 저장소**. 배포본은 `GoogleChrome/modern-web-guidance`(빌드 산출물), npm 패키지 `modern-web-guidance` |
| 쓰임 | Agent Skill + CLI. `npx modern-web-guidance@latest install` 로 에이전트(Claude Code, Codex 등)에 skill 을 깐다. 에이전트가 `search "<2–5단어 영어 질의>"` → `retrieve "<id>"` 로 필요한 가이드만 컨텍스트에 끌어온다. `legacy-scan <경로> --json` 은 낡은 패턴 탐지(가이드의 약 20% 만 규칙이 있음) |
| 동기 | LLM 학습 데이터에 낡은 코드가 많아 JS 를 부풀리고 네이티브 해법(`<dialog>`, popover, anchor positioning, view transitions 등)을 놓친다. 평가(evals)로 "모델이 이미 아는 내용"을 잘라 토큰을 아낀다 |
| 규모 | `guides/` 아래 약 250개 가이드 디렉터리(18개 범주: accessibility, css, forms, html, js, performance, security, privacy, pwa, ui-atoms, ui-behaviors, ui-components, user-experience, visual-design, built-in-ai, wasm, webmcp 등). 범주 루트 가이드(`accessibility`, `css`, `html`, `forms`, `performance`, `security`, `js`, `color`, `typography`, `dark-mode`, `motion` 등)가 "규율 가이드"(DISCIPLINE_GUIDES) |
| 가이드 1개 구성 | `guide.md`(런타임에 에이전트가 읽는 유일한 파일), `demo.html`(기준 구현), `expectations.md`(시험 가능한 `MUST`/`MUST NOT` 문장 — 전체 약 670줄, 213 파일), `targets/`(평가용 앱 캡슐 `daily-grind`, `devtools-times`) |
| 평가 | `gd dev` 파이프라인이 expectations 를 Playwright grader 로 바꿔, **가이드 있음/없음** 에이전트를 비교한다(Claude Code, Codex CLI 등). 결과 대시보드 공개 |
| 스택 | TypeScript(Node), pnpm, oxlint. `src/analyzing/rules/*.ts`(80개 legacy-scan 규칙, `keepWhen/dropWhen` 루브릭), `src/rag`(의미 검색) |
| 라이선스 | **코드 Apache-2.0**, **`guides/` 문서·가이드 내용 CC-BY 4.0**(MDN·W3C·WHATWG 일부 파생). 가이드를 가져다 쓰려면 출처·변경 표시 필요 |
| 유지 상태 | 매우 활발. 마지막 커밋 2026-11-13(PR #3524번대). Chrome·Edge·Firefox·MDN 팀이 관리(GOVERNANCE.md, ATL 제도, 단계 파이프라인 Stage1 사용례 → Stage2 가이드 → Stage3 평가). CLA 필요 |
| 텔레메트리 | 설치 수, 호출 에이전트명, retrieve ID, **search 질의문**을 Google 로 보냄. `DISABLE_TELEMETRY=1` 로 끈다 |
| 기능 안정도 정책 | 기본 가이드는 **Baseline Widely available** 대상. Newly/Limited 기능은 폴백 필수. 한 엔진만 낸 지 3개월 미만(volatile)·Origin Trial 은 검색엔 보이나 retrieve 가 막히고 `.mwgrc` 로 옵트인해야 한다 |

핵심 파일: `S:README.md`, `S:AGENTS.md`, `S:docs/CONTEXT.md`, `S:guides/CONTRIBUTING.md`, 런타임 skill 본문은 `S:guides/modern-web-guidance/SKILL.md`.

SKILL.md 흐름: (1) 웹 UI/CSS/클라이언트 JS 작업 **시작 전** search → (2) 맞는 id + 해당 규율 가이드를 retrieve → (3) 구현이 가이드(폴백 포함)를 지켰는지 대조 → (4) 응답 끝에 `### Modern Web Guidance` 절로 어떤 가이드가 어떤 비자명한 선택을 만들었는지 가이드 원문 한 구절 인용과 함께 공개. 백엔드·인프라·잡다한 수정에는 쓰지 않는다.

## 2. herdr-team 에 이미 있는 것 (중복 제안 금지)

`design-rules.md` 가 이미 다룬다: 이모지·왼쪽 줄·그라디언트 금지(§1), 네이티브 요소 우선·`:focus-visible`·키보드·`<dialog>`·타깃 크기·라벨·`aria-invalid`·reduced-motion·라이브 리전(`status`/`alert`)·`lang`·`main`·skip link·200% 확대/320px(§2), 색 램프·토큰 역할·대비(§3), 글꼴 3개·rem·줄간격·`keep-all`·`text-wrap`·`tabular-nums`(§4), 간격 묶음·터치 영역·`max-width` 상자(§5), transition 규칙·`all` 금지·`@media (hover:hover)`·`overscroll-behavior`(§6), 상태 10종·삭제 확인·오류 문구(§7), 즉시 차단 10항목. 자동 검사: 이모지·왼쪽 줄·파랑→보라(`lint.py`), 지운 줄의 접근성 신호, 확대 막기·`outline:none`.
`review-design.md` 1–9, `text-rules.md`/`textlint.py`, `designdiff.py`, tester 의 전체 테스트 분류도 있다.
출처로 jakubkrehel/skills(MIT)를 이미 표기해 둔 선례가 있다 → 이번 항목도 같은 방식(요약 재작성 + 출처 표기)이 맞다.

## 3. 제안 항목

표기: **그대로** = 거의 그대로 채택 / **적응** = 우리 규칙 형식·한국어에 맞게 고쳐 채택 / **참고** = 아이디어만.

### (a) 프로젝트 프로세스(기획·분해·검증)

| # | herdr-team 대상 | 제안 | 출처 | 근거 | 판정 |
|---|---|---|---|---|---|
| A1 | `roles/planner.md` "tasks.toml 형식"의 수용 기준, `roles/tester.md` 품질 기준 | 수용 기준을 "구현은 X 해야 한다 / Y 하면 안 된다" 식 **관찰 가능한 단문**으로 쓰게 하고 tester 가 문장마다 시험·시나리오 1개를 대응. 지금 tester 는 "수용 기준마다 테스트 하나"까지만 있고 문장 모양 규칙은 없다 | `S:guides/accessibility/accessibility/expectations.md` (MUST/MUST NOT 목록) | 모호한 기준이 리뷰 왕복의 원인. Google 도 같은 방식으로 grader 를 자동 생성 | 적응 |
| A2 | `roles/developer.md` "품질 기준" 앞에 "구현 전 조회" 한 줄, 신규 `templates/web-platform.md`(아래 B 항목 모음) | 웹 UI 작업은 **자체 구현·라이브러리 추가 전에** 네이티브 해법을 먼저 확인한다(`dialog`/`popover`/`details`, `:user-invalid`, `light-dark()`, `text-wrap`, `scheduler.yield` 등). SKILL.md 의 "search first, 의존성 추가 전" 원칙 | `S:guides/modern-web-guidance/SKILL.md` Step 1–2 | developer 가 `div` 모달·JS 스크롤 리스너·무거운 폴리필로 가는 것을 앞에서 막는다. `review-prompt` 의 교차 리뷰는 사후라 늦다 | 적응 |
| A3 | `templates/review-design.md` 신규 기준 10, 보고서의 `### 디자인 점검`(또는 새 소절 `### 웹 플랫폼 점검`) | SKILL.md Step 3·4 를 흉내: developer 는 쓴 네이티브 해법·폴백과 **막은 함정**을 항목당 1–2문장으로 적고, 리뷰어는 그 주장이 코드와 맞는지 대조. 공개문에는 규칙 원문 구절 인용을 요구해 "기억으로 지어낸 인용"을 걸러낸다 | `S:guides/modern-web-guidance/SKILL.md` Step 4 | 이미 `### 디자인 점검` 이 있으므로 새 절보다 §8(성능)·§9(플랫폼) 항목을 거기에 넣는 편이 가볍다 | 적응 |
| A4 | `roles/tester.md` "품질 기준" + `docs/qa/<key>.md` 템플릿 | 자동 접근성 점검(Lighthouse 접근성 감사 — chrome-devtools MCP `lighthouse_audit` 이 이미 있음)과 **키보드만으로 전 화면 통과**(Tab/Shift+Tab/화살표/Enter/Space/Esc)를 QA 시나리오에 필수로. "점수 100이 사용성을 보장하지 않는다"를 보고서에 적게 한다 | `S:guides/accessibility/accessibility/guide.md` §13 Testing Validations | tester 에 접근성 시험 항목이 지금 없다(design-rules 는 designer·developer·리뷰어 대상) | 그대로 |
| A5 | `templates/design-rules.md` §0 신규 "Baseline 정책" 한 줄 + `roles/developer.md` | 기본은 Baseline Widely available. 새 기능은 `@supports`/기능 검사로 **폴백 필수**. Origin Trial·한 엔진 전용(Chrome 전용 Interest Invokers·customizable select 등)은 쓰지 않는다. 꼭 필요하면 ask 로 메인에 묻는다(§0 의 "시스템에 없는 값" 처리와 같은 방식) | `S:guides/CONTRIBUTING.md` "Feature Stability" 표, `S:features/volatile-features.json` | 지금 규칙은 브라우저 지원 기준이 없어 designer 시안(`index.html`)이 실험 CSS 로 갈 수 있다 | 적응 |
| A6 | planner(기존 코드가 있는 프로젝트) 인터뷰 체크리스트 / `roles/developer.md` "리팩터링" | 현대화 요청 때만 `legacy-scan`을 읽기 전용 점검으로 돌리고, 각 지적을 `keepWhen/dropWhen` 으로 걸러 거짓 양성을 버린 뒤 태스크로 쪼갠다. 특정 기능 작업 중엔 돌리지 않는다(SKILL.md 가 명시) | `S:guides/modern-web-guidance/SKILL.md` "Alternative flow", `S:src/analyzing/` | 브라운필드 프로젝트용. 스캐너는 약 20% 만 덮고 npx·네트워크가 필요 → 선택 사항 | 참고 |
| A7 | 설계 문서(`docs/superpowers/specs/`)의 규칙 유지보수 절 | "모델이 이미 아는 내용은 잘라 토큰을 아낀다" + 가이드 **A/B 평가**(규칙 있음/없음으로 같은 작업을 돌려 grader 로 비교). 우리 design-rules 가 실제로 위반을 줄이는지 `designdiff.py`/lint 로 측정하는 후속 작업의 틀 | `S:docs/EVALS.md`, `S:docs/CONTEXT.md` §2, `S:src/grading/` | 규칙이 길어질수록 워커 컨텍스트 비용이 커진다. 지금은 규칙 추가만 있고 가지치기 기준이 없다 | 참고 |
| A8 | 설치 방식(`hteam setup` 또는 프로젝트 `.claude/skills`) | 이 skill 을 **워커 환경에 직접 설치하지 않는다**. 네트워크 npx 실행·텔레메트리(search 질의 전송)·전역 파일 변경이 따른다(메모리 규칙 "ops safety: 플러그인 설치·전역 설정 금지"와 충돌). 대신 필요한 가이드 내용을 요약해 `templates/` 에 넣는 쪽을 택한다 | README "Telemetry & Privacy" | 사용자 환경 불변·재현성·오프라인 워커 유지 | 참고(설치 비권장) |

### (b) 디자인 품질(웹/앱 UI·접근성·성능·최신 플랫폼)

기존 `design-rules.md` 에 **빠진** 것만 적었다.

| # | 대상 위치 | 제안 | 출처 | 근거 | 판정 |
|---|---|---|---|---|---|
| B1 | `design-rules.md` §3 새 항목(색) | `<meta name="color-scheme" content="light dark">` + `:root{color-scheme: light dark}` 로 선언해 스크롤바·폼 컨트롤·캔버스가 테마를 따르게 하고(FOUC 방지), 다크 토큰은 `light-dark(a, b)` 로 한 곳에서 정의. 날 값(`--c-light`,`--c-dark`)은 따로 둬 폴백이 쉽게. 테마를 지원하는 프로젝트에만 적용 | `S:guides/visual-design/dark-mode/guide.md` | §6.11(테마 전환 효과 끄기)만 있고 테마 구현법이 없다. 다크 모드 시안·구현이 어긋나는 흔한 원인 | 적응 |
| B2 | `design-rules.md` §2 새 항목 + 즉시 차단 후보 | **Forced Colors Mode**(Windows 고대비): `box-shadow`·그라디언트·`background-image` 로만 경계·구분·상태를 표현하지 않는다(사라진다). `forced-color-adjust: none` 은 색 자체가 정보인 곳(색 선택 견본)에만. 필요하면 `@media (prefers-contrast: more)` 로 옅은 경계·보조 글자 보강 | `S:guides/visual-design/color/guide.md` Forced Colors/Contrast | §2.9 는 "색만으로" 만 다룬다. 현재 규칙은 §6.2(높이감=그림자) 때문에 오히려 그림자에 의존할 수 있어, 구조는 테두리라는 §6.2 와 맞물려 보강하면 된다 | 그대로 |
| B3 | `design-rules.md` §3 항목 2(램프 생성) | 색 단계를 동적으로 만들 때 `oklch(from …)` 로 **명도만 바꾸지 않는다**(브라우저가 gamut mapping 을 아직 안 해 결과가 불안정). `color-mix(in oklab, …, white/black)` 를 쓰고 명도 보정은 30% 이하로 섞는다. 가능하면 미리 정한 토큰 우선 | `S:guides/visual-design/color/guide.md` "Generating tints" | director 가 램프를 만들 때의 구체 방법이 없다("색 도구로 만든다"만 있음) | 적응 |
| B4 | `design-rules.md` §6 새 항목(움직임) | 움직임은 `opacity`·`transform`(개별 `translate`·`scale`) 만 애니메이션(compositor 스레드). 높이 접기/펼치기에 `max-height`·`height`·`left/top` transition 을 쓰지 않는다(필요하면 `interpolate-size`/`calc-size()` 또는 `<details>`). 대화창·popover 진입/퇴장은 `@starting-style` + `transition-behavior: allow-discrete` + `overlay`. 끈 뒤에도 요소는 **최종 상태**로 남는다(`opacity:0` 로 숨은 채 방치 금지). 1초에 3번 넘는 번쩍임 금지(reduced-motion 과 무관하게 적용) | `S:guides/ui-behaviors/motion/guide.md`, `S:guides/ui-behaviors/animate-element-entry-exit` | §6.3 은 `all` 금지와 속성만 적는 정도. 레이아웃 속성 애니메이션과 번쩍임 한도는 없다 | 그대로(번쩍임 한도는 즉시 차단 후보) |
| B5 | `design-rules.md` §2.7·§7 오류 상태, `roles/developer.md` | 검증 시점 표: `input`=기존 오류 **지우기만**, `blur`(수정했다면)=검사·표시, `submit`=막고 첫 오류/요약으로 포커스. 오류 표시 CSS 는 `:invalid` 가 아니라 `:user-invalid`(비어 있는 필수칸이 처음부터 빨갛게 되는 것 방지). 매 키 입력마다 `aria-live` 로 오류를 읽지 않는다. 유효 제출 **뒤에는** 버튼을 비활성화해 중복 전송 방지. 클라이언트 검증은 UX 용, 보안은 서버 | `S:guides/forms/forms/guide.md` §4 | §2.7 은 "제출할 때 검사"만 있어 blur 규칙·`:user-invalid`·중복 전송이 빠졌다(충돌은 아래 §4 참조) | 적응 |
| B6 | `design-rules.md` §2 구조·이름 보강 | 제목 단계 건너뛰지 않기, `<h1>` 화면당 하나(모달 `<dialog>` 안은 예외), 가짜 제목(`div` 큰 글자) 금지, `<summary>` 안에 제목 넣지 않기. 데이터 표는 `<caption>`+`<th scope>`, 레이아웃용 `<table>` 금지. 반복 내비게이션이 둘 이상이면 `<nav aria-label>` 로 구분하고 `<section>` 에 이름 붙여 `region` 을 남발하지 않는다. 같은 모양의 "수정"·"삭제" 버튼이 여럿이면 대상을 이름에 포함(보이지 않는 글자·`aria-label`). 접근 가능한 이름에 역할 낱말("버튼")을 넣지 않는다. `title`/`placeholder` 로 이름을 대신하지 않는다. `<iframe title>`, 인라인 `<svg>` 는 `aria-hidden` 또는 `role="img"`+이름, 말이 있는 `<video>` 는 `<track kind="captions">`, 토글은 `aria-expanded`/`aria-pressed` | `S:guides/accessibility/accessibility/guide.md` §1–§6, `expectations.md` | §2.13 은 `main`·`lang` 정도. 이 항목들이 접근성 검토에서 가장 자주 나오는 구체 위반 | 그대로(한국어로 재작성) |
| B7 | `design-rules.md` §4 항목 6(줄 길이) | "줄 길이 상한"에 수치를 준다: `max-width: 60ch`(≈ 영문 80자). 단 한글은 `ch` 환산이 달라 우리 값을 따로 정할 것. `hyphens: auto` 는 `lang` 이 선언된 때만. 고정 `height` 를 텍스트가 든 버튼·탭·배지에 쓰지 않는다(`min-block-size`) | `S:guides/visual-design/typography/guide.md` | 수치 없는 "상한"은 리뷰 합의가 안 된다 | 적응 |
| B8 | `design-rules.md` 신규 §8 "성능"(UI 를 만드는 모든 역할의 짧은 점검표) | LCP 이미지는 `loading="lazy"` 금지·초기 HTML 에 있어야 함·`fetchpriority="high"` 는 하나만. 모든 `<img>`/`<video>` 에 `width`·`height` 또는 `aspect-ratio`(CLS). `srcset` 에는 `sizes`. 렌더 차단 방지: 비핵심 스크립트 `defer`/`async`, CSS `@import` 금지, 미디어 쿼리로 CSS 분리. 웹폰트는 쓰는 굵기만, `preload`+`font-display: swap`(§4.2 와 연결). 긴 화면 아래쪽에 `content-visibility: auto`(위쪽·작은 페이지엔 금지). `will-change` 를 전역에 쓰지 않는다. JS: 50ms 미만 동기, 50–250ms 는 `scheduler.yield()` 로 쪼개기, 250ms 초과는 Worker, 읽기/쓰기 섞인 레이아웃 스래싱 금지 | `S:guides/performance/performance/guide.md` (CRP/LCP/INP/이미지/폰트/code-splitting 절) | 지금 design-rules 에 성능 절이 **없다**. 기준이 없어 리뷰가 성능을 판정하지 못한다 | 적응 |
| B9 | `design-rules.md` §2.4 옆 신규 "오버레이 선택표" | `<dialog>`=사용자 응답이 필요한 중단(모달 포커스 자동 가둠, Esc/폼으로 닫기), `[popover]`=가벼운 일시 정보(메뉴·툴팁·토스트, light-dismiss), `<details>`=인라인 펼침(아코디언·FAQ). 모달 뜬 동안 배경 스크롤 방지, 위치 지정은 Anchor Positioning(폴백 포함) | `S:guides/html/html/guide.md` §4 "Native UI Overlay & Disclosure Matrix", `S:guides/ui-components/dialog` | §2.4 는 `<dialog>` 만 있다. 메뉴·툴팁·토스트를 JS 로 만드는 쪽을 막는 표다 | 그대로 |
| B10 | `roles/director.md` 단계 ③ 시스템(토큰 구조) | 토큰 계층 안내: 리터럴(`--color-blue-10`) → 의미(`--color-accent`) → 일반 UI(`--ui-border`) → 컴포넌트(`--button-bg-primary-hover`). **작은 범위는 1단계면 충분**("과설계 금지"). 코드에 의미 없는 값 직접 쓰기 금지(`#f06`, `.3em` 불가, `0`·`transparent` 는 허용) | `S:guides/css/css/guide.md` §5 | §3.3 이 2단계(기본/의미)만 말한다. 계층 수의 기준이 없다. developer.md 의 "하드코딩 금지"와 일치 | 참고 |
| B11 | `designer.md`/`director.md` 아이콘 규칙 | 아이콘은 `currentColor` 로 글자색을 따르고 라이트/다크 모두 배경 대비 3:1. 기법 선택: CSS 가 고르면 mask(단색)/배경(다색), 내부 스타일링이 필요하면 인라인 SVG, `<img>`+CSS 필터로 색 바꾸기 금지 | `S:guides/ui-atoms/icons/guide.md` | §6.10 는 굵기만. 구현 기법이 빠졌다 | 적응 |
| B12 | `design-rules.md` §7 상태에 사용자 환경 선호 | `prefers-reduced-motion`·`prefers-color-scheme`·`prefers-contrast`·`forced-colors`·로케일·데이터 절약(`Save-Data`/느린 연결·오프라인) 선호를 상태 축으로 확인한다 | `S:guides/user-experience/preference-aware-ui` | §7.1 상태 목록에 "환경 설정 축"이 없다 | 적응 |

### (c) 코드 품질(자동 검사 후보)

`lint.py` 는 변경 파일을 정규식으로 훑어 리뷰 프롬프트에 의심 위치를 싣는다. 아래는 같은 방식으로 추가할 수 있는 검사로, 모두 expectations.md/guide 의 MUST 에서 나왔다(거짓 경고 가능 → 판정은 리뷰어).

| # | 검사 | 대응 규칙 | 출처 |
|---|---|---|---|
| C1 | `transition`(-property)에 `all`·`max-height`·`height`·`width`·`top`·`left` | B4 / §6.3 | `S:src/analyzing/rules/animate-to-intrinsic-sizes.ts` (legacy-scan 규칙 모양을 그대로 참고) |
| C2 | CSS `@import`, `<script src>` 에 `defer/async/type=module` 없음(head 안) | B8 | performance 가이드 CRP |
| C3 | `<img>`/`<video>` 에 `width`·`height`/`aspect-ratio` 없음, 첫 이미지에 `loading="lazy"`, `srcset` 에 `sizes` 없음 | B8 | performance 가이드 |
| C4 | `<html>` 에 `lang` 없음, `<iframe>` 에 `title` 없음, 인라인 `<svg>` 에 `aria-hidden`/`role="img"` 없음, `tabindex="[1-9]"`, `<div|span ... onclick>`/`role="button"` | §2 / B6 | a11y `expectations.md` |
| C5 | `<table>` 에 `<caption>`·`<th scope>` 없음, `<h1>` 둘 이상, 제목 단계 건너뜀, `<summary>` 안 `<h*>` | B6 | a11y guide §1 |
| C6 | CSS `:invalid` 단독 선택자(→ `:user-invalid`), `font-size: …px`, 전역 `will-change` | B5, §4.5 | forms/typography/performance |
| C7 | 보고서 `### 디자인 점검` 에 "확인 못 함" 만 적은 경우 경고 — SKILL.md Step 3·4 의 대조 개념 | A3 | SKILL.md |

구현 노트: 이미 `lint.py` 가 HTML/JSX/Tailwind 를 줄 단위로 보는 구조이므로 C1–C6 은 `scan()` 에 규칙을 추가하는 형태가 자연스럽다. `designdiff.py` 의 "지운 줄" 신호 목록에는 `aria-expanded`/`aria-pressed`·`title`(iframe)·`<caption>`·`scope` 를 더할 수 있다.

## 4. herdr-team 현재 규칙과 충돌하는 점

| # | 충돌 | 판단 |
|---|---|---|
| X1 | 가이드 예시 코드가 이모지 오류 아이콘(`<span aria-hidden="true">❌</span>`)을 쓴다(`S:guides/visual-design/color/guide.md`). design-rules §1.1 은 이모지를 상태 표시로 쓰는 것을 금지 | 코드 예시를 그대로 옮기지 말고 시스템 아이콘 세트 SVG 로 바꾼다 |
| X2 | 오류 검사 시점: 우리 §2.7 은 "제출할 때 검사", 가이드는 "수정한 필드는 blur 에서 검사·표시" | 모순은 아니다(입력 중 비검사는 공통). B5 처럼 §2.7 에 blur 를 **허용**하는 문장을 추가해 맞춘다 |
| X3 | reduced-motion: 우리 §2.10 은 `no-preference` 안에서만 움직임. 가이드는 "애니메이션을 아예 없애면 `no-preference`, 파라미터만 바꾸면 `reduce`" 로 둘 다 허용 | 우리 규칙이 더 엄격하며 가이드와 양립. 바꾸지 않는다. 단 "전역 `animation-duration: 0.01ms` 금지"는 우리에 없으니 B4 에 추가 |
| X4 | 가이드는 "접근성은 최소선이지 상한이 아니다 / 점수 100은 보장 아님". 우리 자동 검사는 "자동 불합격이 아니다"로 이미 같은 방향 | 충돌 아님 |
| X5 | SKILL.md Step 4 의 응답 끝 `### Modern Web Guidance` 공개 절과 영어 인용 요구 | 우리 보고서 구조(`## rN` 안 `### …`)·한국어 규칙과 다르므로 별도 절을 신설하지 말고 `### 디자인 점검` 안에 흡수(A3). 영어 인용을 강제하지 않는다 |
| X6 | 운영 안전: skill 설치는 `npx` 네트워크 호출·전역/프로젝트 설정 변경·텔레메트리(질의문 전송)를 수반 | 사용자 메모리 규칙(플러그인 설치·전역 설정 금지)과 충돌 → A8 대로 직접 설치하지 않고 내용만 흡수 |
| X7 | 가이드는 Chrome 팀 주도라 Chrome 우선 기능(Interest Invokers, customizable select, `focusgroup`, 일부 anchor/scroll-state)이 상당수. 우리는 실사용 브라우저 범위를 정한 적이 없고 designer `index.html` 은 외부 리소스를 못 쓴다 | A5 의 Baseline 정책으로 제어. volatile 목록은 `features/volatile-features.json`·`pending-web-features.json` 에서 확인 |
| X8 | `legacy-scan` 은 가이드의 약 20% 만 덮는데 `retrieve` 와 혼동하기 쉽다(SKILL.md 가 특정 기능 작업에서는 돌리지 말라고 명시) | 도입 시 "현대화 요청에서만" 이라고 못박는다 |
| X9 | 라이선스: CC-BY 4.0 이라 요약·재작성은 가능하나 출처·변경 표시가 필요하다. 현재 design-rules 의 "출처" 절은 jakubkrehel 만 적었다 | 흡수 후 "출처" 절에 이 저장소(CC-BY 4.0, 커밋 해시, 날짜)를 추가 |

## 5. 우선순위 권고

1. **B8(성능 §8)**, **B6(구조·이름 보강)**, **B2(Forced Colors)**, **B4(레이아웃 속성 애니메이션·번쩍임)**, **B9(오버레이 표)** — 현재 규칙에 구멍이 가장 확실하고 한국어 재작성만으로 끝난다.
2. **A4(tester 접근성 시험)**, **A1(수용 기준 문장 모양)**, **A5(Baseline 정책)** — 프로세스 공백이며 비용이 작다.
3. **C1–C6(lint 추가)** — B 항목이 확정된 뒤 같은 PR 에서. 기존 설계(기계 검사 = 의심 위치, 판정 = 리뷰어)를 유지.
4. 참고만: A6–A8, B10, 평가 하니스(A7).

주의: 흡수할 때 규칙을 늘리기만 하면 워커 컨텍스트가 커진다(이 프로젝트가 평가로 "이미 아는 내용"을 잘라내는 이유). 모델이 이미 잘 지키는 항목(네이티브 요소 우선, `alt` 등)은 이미 §2 에 있으니 되풀이하지 않았다.
