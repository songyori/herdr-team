# 웹 플랫폼 규칙

웹 UI(브라우저에서 도는 화면과 그 시안)를 만들거나 시험하는 designer·developer·tester 와 디자인 리뷰어가 `.herdr-team/design-rules.md` 와 함께 읽는다. 앱(iOS·Android·Flutter)만 만드는 태스크는 읽지 않는다. design-rules 가 무엇을 지킬지 정하고, 이 파일은 그것을 웹 플랫폼 기능으로 어떻게 만드는지 정한다. 어긴 곳과 예외·근거는 design-rules 와 같이 보고서 `### 디자인 점검` 에 적는다.

## §0 범위
- 프로젝트 디자인 시스템과 기술 스택이 정한 것이 먼저다(design-rules §0). 이 파일과 다른 방식이 필요하면 designer 는 `### 시스템 추가 제안` 에 적고, developer 는 프리앰블의 ask 명령으로 메인에게 묻는다.
- 검사 방식 표기는 design-rules §0 과 같다: `[기계]` 는 hteam 자동 검사가 의심 위치를 찾는다(design-rules 의 "자동 검사" 절. 경고가 없다고 지킨 것은 아니다), `[렌더]` 는 화면을 렌더해야 안다, `[판단]` 은 읽고 판단한다.

## §1 Baseline
1. 기본은 Baseline Widely available(주요 브라우저가 모두 오래 지원한) 기능이다. 그보다 새 기능(Newly available, Limited)은 `@supports`·기능 검사와 폴백을 함께 둘 때만 쓴다. [판단]
2. 한 엔진에만 있는 기능과 Origin Trial 은 쓰지 않는다. 꼭 필요하면 developer 는 프리앰블의 ask 명령으로 메인에게 묻고, designer 는 `### 시스템 추가 제안` 에 적는다. [판단]
3. 직접 만들거나 라이브러리를 더하기 전에 네이티브 해법(`<dialog>`, `popover`, `<details>`, `:user-invalid`, `light-dark()`, `text-wrap`)을 먼저 본다. [판단]

## §2 오버레이
1. 응답이 있어야 하는 중단(확인, 필수 입력)은 `<dialog>` 를 `showModal()` 로 띄운다(포커스는 design-rules §2 의 4). [판단]
2. 메뉴·툴팁·토스트처럼 가벼운 일시 정보는 `popover` 속성으로 띄운다. [판단]
3. 인라인 펼침(아코디언, 자주 묻는 질문)은 `<details>`·`<summary>` 로 만든다. [판단]
4. 모달이 떠 있는 동안 뒤 페이지가 스크롤되지 않는다. [렌더]
5. 앵커 위치 지정(`anchor-name`·`position-anchor`)은 지원하지 않는 브라우저의 폴백 위치와 함께 쓴다. [판단]

## §3 폼 검증 시점
1. 입력하는 동안에는 이미 보인 오류를 지우기만 하고 새 오류를 띄우지 않는다. 고친 칸은 포커스가 떠날 때(blur) 검사해 보인다. 제출에서 막고 첫 틀린 칸으로 포커스를 옮긴다(design-rules §2 의 7). [판단] [렌더]
2. 오류 모양은 `:invalid` 가 아니라 `:user-invalid` 에 건다(손대기 전의 빈 필수 칸이 처음부터 오류로 보이지 않게). [판단]
3. 키 입력마다 `aria-live` 로 읽히게 하지 않는다. [판단]
4. 유효하게 제출한 뒤에는 응답이 올 때까지 같은 제출을 다시 보내지 않게 막는다. [판단]
5. 클라이언트 검증은 사용성을 위한 것이다. 보안과 데이터 검사는 서버가 한다. [판단]

## §4 테마·색 구현
1. 밝은·어두운 테마를 지원하면 `<meta name="color-scheme">` 과 CSS `color-scheme` 을 선언하고, 테마별 색은 `light-dark()` 로 한곳에서 정의한다. [판단]
2. 단계 색(hover·눌림 등)은 시스템이 미리 정한 토큰을 먼저 쓴다. 만들어야 하면 `oklch(from …)` 로 명도만 바꾸지 않고 `color-mix(in oklab, …)` 로 섞는다. [판단]

## §5 움직임 구현
1. `opacity`·`transform`(`translate`·`scale`)만 움직인다. `height`·`max-height`·`width`·`top`·`left` 와 `all` 을 transition 하지 않는다. 높이 펼침은 `interpolate-size: allow-keywords` 나 `<details>` 로 한다. [판단]
2. 나타나고 사라지는 전환은 `@starting-style` 과 `transition-behavior: allow-discrete` 로 한다. 전환이 끝난 요소는 최종 상태로 남긴다(`opacity: 0` 으로 숨긴 채 두지 않는다). [판단]
3. 1초에 3번 넘게 번쩍이지 않는다. 동작 줄이기 설정과 상관없이 지키는 즉시 차단 항목이다. [렌더] [판단]

## §6 성능
1. LCP 이미지(첫 화면의 가장 큰 그림)는 `loading="lazy"` 를 쓰지 않고 초기 HTML 에 둔다. `fetchpriority="high"` 는 그 하나에만 둔다. [판단]
2. 모든 `<img>`·`<video>` 에 `width`·`height` 나 `aspect-ratio` 를 둔다(늦게 온 그림이 레이아웃을 밀지 않게). `srcset` 에는 `sizes` 를 함께 둔다. [판단]
3. 첫 화면에 필요 없는 스크립트는 `defer`·`async` 로 불러온다. [판단]
4. CSS `@import` 로 스타일시트를 잇지 않는다(요청이 차례로 걸린다). 빌드 도구가 하나로 합치는 가져오기와 Sass 의 가져오기는 괜찮다. [판단]
5. 웹폰트는 쓰는 굵기만 불러오고, 첫 화면에 쓰는 글꼴 파일은 `preload` 한다(design-rules §4 의 2). [판단]
6. `content-visibility: auto` 는 첫 화면 아래 영역에만 쓴다. [판단]
7. `will-change` 는 움직이기 직전 그 요소에만 두고 끝나면 지운다. 늘 켜 두지 않는다. [판단]
8. 50ms 넘는 작업은 `scheduler.yield()` 로 쪼개고, 250ms 넘는 계산은 Worker 로 보낸다. [판단]
9. 레이아웃 값을 읽고 쓰는 일을 번갈아 해서 레이아웃을 거듭 계산하게 하지 않는다(읽기를 모은 뒤 쓴다). [판단]

## §7 구조·이름
1. 제목 단계를 건너뛰지 않는다. `<h1>` 은 화면에 하나다(모달 `<dialog>` 안은 따로 센다). [판단]
2. 큰 글자 `div` 로 제목을 흉내 내지 않는다. [판단]
3. 데이터 표에는 `<caption>` 과 `<th scope>` 를 둔다. 레이아웃에 표를 쓰지 않는다. [판단]
4. 내비게이션이 둘 이상이면 `<nav aria-label>` 로 가른다. [판단]
5. 같은 모양의 "수정"·"삭제" 버튼이 여럿이면 접근 가능한 이름에 대상을 넣는다(예: "주문 1024 삭제"). [판단]
6. 접근 가능한 이름에 역할 낱말("버튼", "링크")을 넣지 않는다. `title`·`placeholder` 로 이름을 대신하지 않는다. [판단]
7. 인라인 `<svg>` 는 장식이면 `aria-hidden="true"`, 정보면 `role="img"` 와 이름을 둔다. [판단]
8. 말이 있는 `<video>` 에는 자막 `<track>` 을 둔다. [판단]
9. `<iframe>` 에는 내용을 말하는 `title` 을 둔다. [판단]
10. 펼치는 토글은 `aria-expanded`, 켜고 끄는 토글 버튼은 `aria-pressed` 로 상태를 알린다. [판단]

## §8 아이콘 구현
1. 아이콘은 `currentColor` 로 글자색을 따르고, 두 테마 모두에서 배경과 대비 3:1 이상이다. [렌더]
2. 단색 아이콘은 CSS `mask` 로, 안쪽 색을 바꿔야 하는 아이콘은 인라인 SVG 로 넣는다. `<img>` 에 CSS 필터를 걸어 색을 바꾸지 않는다. [판단]

## 리뷰 등급
- 즉시 차단(보고서에 예외를 적었어도 리뷰어는 P1(REQUEST_CHANGES)로 판정한다): §5 의 3 번쩍임, 그리고 §7 을 어겨 이름이 없는 컨트롤이나 §3 을 어겨 복구 방법을 알려 주지 않는 오류처럼 이 파일을 어겨 design-rules `## 즉시 차단 항목` 에 해당하게 된 것.
- 그 밖의 위반은 P2 다. 보고서 `### 디자인 점검` 에 적은 예외의 근거가 타당하면 지적하지 않는다(design-rules §2–§7 과 같다).

## 출처
13단계(2026-11-16 조사)에 GoogleChrome/modern-web-guidance(원본 저장소 https://github.com/GoogleChrome/modern-web-guidance-src, 가이드 문서 CC-BY 4.0, 2026-11-13 커밋)의 가이드(accessibility, forms, motion, color, performance, preference-aware-ui 등)를 골라 줄이고 한국어로 새로 썼다(원문을 옮기지 않았다). 데이터 표 머리글 같은 접근성 점검은 addyosmani/agent-skills(https://github.com/addyosmani/agent-skills, MIT, 2026-11-13 커밋)를 참고했다.
