# 5. AI 티(anti-slop) 디자인 조사 — 색·글꼴·레이아웃·한국어 문구 다양성

- 조사일: 2026-11-16. GitHub 원본(raw 파일, `gh api`), npm 메타, 공식 문서 페이지를 우선했다. 별 개수와 라이선스는 `gh api repos/<repo>` 의 그날 값이다.
- 표시: **(불확실)** 은 원문을 확인하지 못한 것, **(기억)** 은 조사 중 원문을 열지 않고 알고 있던 값이다.
- 저장소 파일은 고치지 않았다. 아래 "적용 제안"은 제안일 뿐이다(CLAUDE.md 절차상 설계 → 계획 → Codex 리뷰를 거친다).

## 0. 요약
1. 획일화의 원인 일부는 herdr-team 템플릿 자체에 있다. director.md 예시가 AI 기본값 묶음을 앵커로 준다(§1). Claude Design quickstart 에 `design_systems: false` 가 없어 계정 기본 시스템 README 가 시안에 붙는다(§1). 그리고 lint 는 단색 기본 강조(#1e3a8a 등)를 잡지 못한다.
2. 근거 있는 다양성 주입 방식이 이미 공개돼 있다. impeccable 은 `palette` 명령(OKLCH 시드 128개, 30° 색상 구간 균등 가중, SHA-256 키 결정)을 쓴다. taste-skill 은 `deal`(팔레트 64개 + 기록 파일)을, Hallmark 는 `theme.mjs deal`(테마 50개 + `.hallmark/log.json` 회전)을 쓴다. 셋 다 "취향으로 고르지 말고 배정(deal)받는다"를 핵심으로 둔다.
3. 그대로 들여올 수 있는 데이터는 다음과 같다. taste-skill `library/palettes.json`(MIT), impeccable 팔레트 시드(Apache-2.0, NOTICE 필요), MetBrewer(CC0), Radix Colors(MIT)다. ColourLovers 계열(nice-color-palettes 데이터), Huemint API, Coolors·Color Hunt·Adobe Color·Pantone 은 들여오지 않는다.
4. 실측: comment-browser `docs/design/system/tokens.json` 은 Pretendard Variable 을 쓴다. 강조·상태색은 Tailwind 기본 램프 값 그대로다(orange-400 #fb923c, orange-700 #c2410c, rose-50/400/700). 중립은 파랑 쪽으로 기운 회색(#7f8697 = oklch(0.620 0.027 267.8))이다. 사용자 예시 #1e3a8a 는 Tailwind v3 `blue-900` 과 정확히 같다.
5. 한국어 쪽: Noto Sans KR·Pretendard 는 한국판 Inter 다. OFL 대안(SUIT, Wanted Sans, IBM Plex Sans KR, Hahmlet, Gowun, MaruBuri, Asta Sans 등)이 충분하다. 문구는 k-skill `korean-humanizer` 분류표가 text-rules.md 에 없는 항목을 20개 가까이 더해 준다.

## 1. 현재 herdr-team 이 획일화를 부르는 지점(저장소 근거)
| 위치 | 내용 | 영향 |
|---|---|---|
| `templates/roles/director.md:47-50` | 레퍼런스 질문 예시가 "차분한 모노톤·넓은 여백: 회색 위계와 강조색 하나" 를 추천안으로 둔다 | 모델이 예시를 그대로 따라 "회색+강조 하나" 로 수렴 |
| `director.md:65` | 톤 시안 예시 표: A 잉크(흰색·먹색 산세리프·강조 하나·4px), B 종이(따뜻한 회백색·세리프 제목·벽돌색·0), C 선명(초록) | B 는 Anthropic frontend-design 이 "AI 생성 디자인의 1번 군집" 이라 부른 "크림 배경+세리프+테라코타" 와 같다 |
| `director.md:95` | 시스템 질문 예시 "주색 #1F6F5C, 본문 Pretendard 16px/1.6" | 프로젝트마다 Pretendard 로 앵커 |
| `director.md:18`(도구 표) | 보드·시안 quickstart 에 `design_systems: false` 가 없다(designer.md 는 있다) | Artifact 도구 설명상 생략하면 "the default one's README" 를 붙인다. 계정 기본 시스템이 모든 프로젝트 시안에 스며들 수 있다(실제 영향 정도는 불확실) |
| `design-rules.md` §3.1·§3.6 | "중립 하나, 강조 하나", "강조색은 배경에" | 원칙은 맞지만 중립이 무엇이어야 하는지, 강조 색상(hue)을 어디서 가져오는지 정하지 않는다. 그 빈칸을 모델 기본값(slate+blue)이 채운다 |
| `design-rules.md` §1.7 | "근거 없이 Inter나 시스템 글꼴" 만 금지 | 한국어 기본값(Noto Sans KR, Pretendard, Apple SD Gothic Neo·맑은 고딕 스택)은 빠져 있다 |
| `director.md` ② 1번 | 톤 3안은 "색, 글꼴, 밀도, 모서리, 그림자 가운데 둘 이상이 달라야" | 색을 바꿔도 같은 파랑 계열 명도만 다를 수 있다. 색상 거리 기준이 없다 |
| `lib/hteam/lint.py:51-53,198-230` | 파랑+보라가 함께 든 그라디언트만 찾는다(HSL 190–300°) | 단색 강조(#1e3a8a), Tailwind 램프 복사, 과용 글꼴은 못 찾는다 |

## 2. 안티 슬롭 스킬·규칙 세트
| 이름 | 링크 | 라이선스 | 신호(2026-11-16) | herdr-team 가 쓸 것 |
|---|---|---|---|---|
| frontend-design (Anthropic) | github.com/anthropics/skills/tree/main/skills/frontend-design | Apache-2.0(스킬 폴더 LICENSE.txt. 저장소 루트는 라이선스 표기 없음) | anthropics/skills 195k★ | AI 군집 5개(hex 포함), 2단계 계획·자기검토, 글자 처리 금지 3개 |
| impeccable (Paul Bakaus) | github.com/pbakaus/impeccable | Apache-2.0, NOTICE.md 있음 | 110k★, SKILL v4.9.1, 11-16 갱신 | antipatterns.json 62개, craft-floor "Refuse", colorize 규칙, `palette` 시드 128개 |
| taste-skill (Leonxlnx) | github.com/Leonxlnx/taste-skill | MIT | 116k★, v2.5.1 | `library/palettes.json` 64개, `type.json` 39개, "Deal, never choose by taste" |
| Hallmark (Nutlope) | github.com/Nutlope/hallmark | MIT | 55k★ | 테마 50개 `references/themes/index.json`, 기록 회전, 분야 반사 색 금지 |
| ui-skills baseline-ui (ibelick) | github.com/ibelick/ui-skills | MIT | 11k★ | 그라디언트·보라 금지, "accent one per view". "MUST use Tailwind defaults" 는 다양성 목표와 부딪쳐 가져오지 않는다 |
| anti-slop (miqdadbadjuber) | github.com/miqdadbadjuber/anti-slop | MIT | 9.3k★ | antislop-ui 의 색 절(파랑-보라 계열, 색 과다, 강조 남발, "정체성 없음" 패턴) |
| web-interface-guidelines (Vercel) | github.com/vercel-labs/web-interface-guidelines | MIT | 1.2k★ | Hue consistency, APCA 권장, theme-color. 대부분 접근성(jakubkrehel 와 겹침) |
| modern-web-guidance (Chrome) | github.com/GoogleChrome/modern-web-guidance | Apache-2.0 | 17.8k★ | 웹 플랫폼 API 지식이다. 미감 규칙은 아니라 이 주제와는 관련이 낮다 |
| DESIGN.md (Google Labs) | github.com/google-labs-code/design.md | Apache-2.0 | 28.9k★, alpha | YAML 토큰+산문 형식. impeccable·Hallmark 가 읽는다. 시스템 사본 내보내기 형식 후보(선택) |
| Refactoring UI 계열 | github.com/LovroPodobnik/refactoring-ui-skill, github.com/wondelai/skills | 앞은 라이선스 없음(63★), 뒤는 MIT(2.7k★) | 커뮤니티 | 책 원칙의 요약이다. 책 내용은 저작물이라 원칙만 참고한다. 우선순위는 낮다 |
| jakubkrehel/skills | github.com/jakubkrehel/skills | MIT | 12.2k★ | 이미 design-rules §2–§7 의 출처 |

### 2.1 Anthropic frontend-design (핵심 규칙 원문 요지)
- "AI-generated design right now clusters around": (1) 따뜻한 크림 배경(#F4F1EA 근처)+고대비 세리프 제목+테라코타 강조(#D97757 근처, Claude 자체 강조색이라 사용자 브리프에서는 티가 난다). (2) 거의 검은 배경+산성 초록이나 주홍 강조 하나. (3) 헤어라인·모서리 0·신문형 단 배치. (4) SaaS 카드 키트: 같은 둥근 카드, 같은 회색 그림자 rgba(0,0,0,.1), 장식 그라디언트. (5) 템플릿 크롬: 모든 제목 위 자간 넓힌 대문자 eyebrow, 'A · B · C' 가운뎃점 메타, 'WORD — fragment', #0B0B0B·#111 근흑, 작은 데이터 라벨의 고정폭, 링크·버튼 끝 '→'.
- "Where the brief pins down a visual direction, follow it exactly … Where it leaves an axis free, don't spend that freedom on one of these defaults."
- 두 단계: 먼저 계획(색은 "4–6 named hex values", 글꼴 역할, ASCII 와이어프레임, 원칙). 그다음 브리프와 대조한다: "work through a similar prompt to see if you arrive somewhere similar". 비슷하면 그 부분을 고치고 무엇을 왜 바꿨는지 말한다.
- 금지 글자 처리: 제목의 한 단어만 기울임·굵게·다른 색, 라벨 전부 대문자, 내용 위 쓸데없는 라벨. 번호 표지(01/02/03)는 실제 순서일 때만.
- "Spend your boldness in one place", "Chanel's advice: … remove one accessory".

### 2.2 impeccable
- `crates/live/assets/antipatterns.json`(62개) 가운데 색·글꼴 관련 id(카테고리 slop):
  - `ai-color-palette`: 보라·바이올렛 그라디언트와 어두운 바탕의 청록 글자
  - `cream-palette`: 크림·베이지 페이지 배경
  - `overused-font`: Inter, Roboto, Fraunces, Geist, Plus Jakarta Sans, Space Grotesk
  - `italic-serif-display`: Fraunces·Recoleta·Playfair 기울임 히어로 제목
  - `gradient-text`, `side-tab`(한쪽 굵은 테두리), `dark-glow`, `radial-halo`, `icon-tile-stack`, `kicker-above-heading`(금지), `gray-on-color`, `gpt-thin-border-wide-shadow`, `codex-grid-background`, `marketing-buzzword`
- `reference/craft-floor.md` "Refuse": 같은 크기의 아이콘+제목+글 카드, 히어로 수치 템플릿, 제목 위 kicker(유일한 절대 금지), 그라디언트 글자, 장식 글래스, 1px 넘는 색 `border-left/right`, 하드 오프셋 그림자, 장식용 고정폭, 이모지 아이콘. "Light or dark picked by category. Pick it from the use scene".
- `reference/colorize.md`: "Choose hue from product meaning and visual direction, never from a default category association." 새 웹 팔레트는 OKLCH. 램프는 흰·검 근처에서 채도를 낮춘다. "Tint neutrals only when the brand hue genuinely creates cohesion. Neutral gray is valid". 색 면 위 보조 글자는 그 면의 hue 에서 뽑는다(회색 금지).
- `palette` 명령(`crates/context/src/palette.rs`, 데이터 `palette_data.rs`):
  - 시드 128개. 각각 OKLCH(L·C·H), 무드 문장, 전략 문장을 갖는다(예: `seed-000` "oxblood leather banquette in a 1940s steakhouse").
  - 30° 구간마다 1/구간 개수로 가중한다. 비어 있지 않은 구간(11개)이 같은 확률로 뽑힌다. 300–330° 구간은 비어 있다.
  - `--from <key>` 나 `IMPECCABLE_PALETTE_SEED` 가 있으면 SHA-256 앞 4바이트로 결정적으로 뽑는다.
  - 템플릿 지침: 주색 hue 는 시드 ±10°다. 배경은 순백 약 50%, 순흑 약 25%, 틴트(C 0.015–0.05) 약 25%이고, 틴트는 환경이 브랜드일 때만 쓴다. ink ≥7:1, muted ≥3.5:1, accent 는 주색과 hue·명도가 둘 다 다르다. 전략은 Restrained·Committed·Full palette·Drenched 중 하나다.
- `concept-seed` 는 원격 roll API 와 사용자별 salt(`~/.impeccable/seed-salt`), 텔레메트리 핑을 쓴다. herdr-team 은 방식만 참고하고 들여오지 않는다.

### 2.3 taste-skill, Hallmark
- taste-skill v2.5.1:
  - "Deal, never choose by taste. Each command keeps a history, so pages differ". `start.mjs deal --trade <trade> --history .taste-skill/history.json` 이 업종에 맞춘 팔레트 3개와 글꼴 짝 3개를 주고 첫째를 쓴다. "never violet: deal again".
  - `library/palettes.json` 64개 항목: `bg`, `surface`, `ink`, `muted`, `accent`, `accentInk`, `fields`, `tags`, `trades`, `note`, `seenIn`.
  - 강조 hue 를 세어 보면 240–300° 는 0개, 210–240° 는 6개이고 나머지가 고르게 퍼져 있다. 글꼴 `type.json` 은 라틴 글꼴 중심으로 보인다(전수 확인 안 함).
- Hallmark:
  - `references/themes/index.json` 50개 항목: `paper{band,L,hue}`, `display{class,face}`, `accent{band,hue}`, `keywords`, `material`.
  - `theme.mjs deal --genre --prompt --log .hallmark/log.json` 이 기록과 겹치지 않는 3개를 준다. 맞춤 색은 `theme.mjs check --hue <h>` 로 카탈로그와 견준다.
  - `references/direction.md` 의 "set aside" 목록: 크림+세리프+클레이, 근흑+네온 하나, "a pale ground with one timid accent", 보라→파랑, "a hue picked for the category, such as blue for software or green for health".

## 3. 색 다양성: 자료와 방법
| 자료 | 기계 사용 | 라이선스 | 쓸 곳 |
|---|---|---|---|
| Radix Colors | npm `@radix-ui/colors` 3.0.0 | MIT | 12단계의 역할 정의(1–2 배경, 3–5 컴포넌트 배경, 6–8 테두리, 9–10 채움, 11–12 글자). 회색 6종(gray 순회색, mauve 보라, slate 파랑, sage 초록, olive 라임, sand 노랑)을 강조 hue 에 맞춰 짝짓는 "natural pairing". 9단계는 흰 글자 기준이고, sky·mint·lime·yellow·amber 는 어두운 글자 기준 |
| Open Color | npm `open-color` 1.9.1 | MIT | 13색×10단계. 오래됐다. 기본값 하나 더 늘리는 셈이라 비추천 |
| Tailwind 팔레트 | npm `tailwindcss` 4.3.5(v4 는 OKLCH) | MIT | 다양성 출처가 아니라 "기본값 목록"의 출처(§4) |
| Material Color Utilities | npm `@material/material-color-utilities` 0.4.0 | Apache-2.0 | HCT. 시드 하나로 전체 scheme 을 만든다. 변형: TonalSpot·Content·Expressive·Fidelity·Vibrant·Rainbow·FruitSalad·Monochrome·Neutral. 같은 시드라도 변형으로 성격이 달라진다 |
| Adobe Leonardo | npm `@adobe/leonardo-contrast-colors` 1.1.0 | Apache-2.0 | 목표 대비비(예: `[2, 3, 4.5, 8]`)로 색을 만든다. "회색 글자 남발"을 비율로 막는다 |
| Harmonizer (Evil Martians) | 웹·Figma 플러그인 | 저장소 라이선스 표기 없음 | OKLCH+APCA 로 같은 단계의 대비를 hue 와 무관하게 맞춘다. 방법만 참고 |
| oklch.com | 웹(`evilmartians/oklch-picker`) | NOASSERTION(불확실) | 사람이 값 확인용 |
| culori / colorjs.io | npm 4.0.2 / 0.7.1 | MIT / MIT | OKLCH 변환·대비 계산. herdr-team 은 표준 라이브러리만 쓰므로 공식만 옮긴다(OKLab 변환은 행렬 2개) |
| apca-w3 | npm 0.1.9 | "LimitedW3License" | 라이선스가 제한적이라 들여오지 않는다 |
| impeccable 시드 | `palette_data.rs` 128개 | Apache-2.0 | 무드 문장+OKLCH 시드. NOTICE 를 붙이면 들여올 수 있다 |
| taste-skill 팔레트 | `library/palettes.json` 64개 | MIT | 완성 팔레트(bg~accentInk)+업종 태그. 들여올 수 있다(저작권 표시) |
| Hallmark 테마 | `themes/index.json` 50개 | MIT | paper·accent hue 축. 회전 기록 방식 참고 |
| Wada Sanzo 『A Dictionary of Colour Combinations』 | npm `dictionary-of-colour-combinations`(348 조합, 159색, CMYK) | 코드·JSON MIT. 원서(1933, 저자 1967 사망) 권리는 불확실 | 2–4색 조합 출처로 이름을 붙일 수 있다. 상업 배포 전 확인 필요 |
| MetBrewer | R 패키지(메트로폴리탄 미술관 작품 팔레트, 색각 이상 점검 표시) | CC0-1.0 | 들여올 수 있다. 데이터·차트 팔레트에 좋다 |
| wesanderson | R 패키지(영화 팔레트) | MIT(+file) | 소량 참고 |
| nice-color-palettes | npm 4.0.0(ColourLovers 상위 팔레트) | 코드 MIT. 데이터는 ColourLovers CC BY-NC-SA 로 알려져 있다(불확실) | 상업 프로젝트용으로 들여오지 않는다 |
| meodai/color-names, poline, rampensau | npm | MIT | 색 이름 붙이기(3만여 개), 앵커 기반 생성, hue 이동 램프 |
| Huemint | 웹 API | about 페이지: "public API for non-commercial applications" | 쓰지 않는다 |
| Coolors(trending), Color Hunt, Adobe Color, Realtime Colors | 웹 도구 | 공개 데이터 라이선스·공식 API 를 확인하지 못했다(불확실) | 레퍼런스 영감으로만 쓰고 수집하지 않는다. Realtime Colors 의 5역할(text, background, primary, secondary, accent)은 계획 틀로 쓸 만하다 |
| Pantone | 상용 | 독점 | 쓰지 않는다 |
| 한국 전통색(오방색 청·적·황·백·흑, 오간색 녹·벽·홍·유황·자) | 공공누리 hex 데이터셋을 찾지 못했다. korean-color-atlas.pages.dev 는 "honest screen approximations" 라고 밝히고 라이선스 표기는 없다 | 불확실 | 이름·개념(무드 문장)으로만 쓰고 값은 디렉터가 OKLCH 로 정한다 |
| 일본 전통색(nipponcolors.com 등) | 웹 | 불확실 | 위와 같다 |

## 4. 기본·과용 강조색 목록(경고 후보)
값은 Tailwind v3.4.17 `lib/public/colors.js`, v4.1.0 `theme.css` 에서 확인했고 OKLCH 는 직접 계산했다.
| 값 | 이름 | OKLCH |
|---|---|---|
| #3b82f6 / #2563eb / #1d4ed8 / #1e40af / #1e3a8a | Tailwind blue-500/600/700/800/900(#1e3a8a 가 사용자 예시) | 900: oklch(0.379 0.138 265.5), 500: oklch(0.623 0.188 259.8) |
| #6366f1 / #4f46e5 / #4338ca | Tailwind indigo-500/600/700 | 500: oklch(0.585 0.204 277.1) |
| #8b5cf6 / #7c3aed, #a855f7 / #9333ea | Tailwind violet·purple-500/600 | violet-500: oklch(0.606 0.219 292.7) |
| #0ea5e9, #10b981 | Tailwind sky-500, emerald-500 | — |
| oklch(62.3% 0.214 259.815), oklch(58.5% 0.233 277.117), oklch(60.6% 0.25 292.717) | Tailwind v4 blue·indigo·violet-500 | — |
| #0f172a, #64748b, #f8fafc / #111827, #6b7280, #f9fafb / #18181b, #71717a | Tailwind slate·gray·zinc 900/500/50 중립 | slate 계열 hue ≈ 255–265 |
| #0d6efd, #007AFF, #6750A4, #6200EE | Bootstrap 5 primary, iOS systemBlue, Material 3 baseline, Material 2 primary(기억) | #0d6efd: h 260.0, #6750a4: h 293.7 |
| #F4F1EA, #D97757, #0B0B0B·#111, rgba(0,0,0,.1) | Anthropic frontend-design 이 꼽은 크림·테라코타·근흑·카드 그림자 | #d97757: oklch(0.672 0.131 38.8) |
- 패턴 규칙 제안: 주 강조(primary·accent 토큰)가 OKLCH h 250–300°, C ≥ 0.08 이면 "파랑·남색·보라 기본 계열"로 근거를 요구한다. 브랜드 자산이나 interview 레퍼런스가 근거가 된다.
- 중립은 C < 0.04, h 250–275°(slate)를 "기본 회청색"으로 본다. 금지가 아니라 근거 요구다(Radix slate 짝짓기는 정당한 선택이다).
- 정확히 일치하는 hex(대소문자 무시)는 "Tailwind 기본 램프 값 N개" 로 묶어 한 번만 알린다. comment-browser 시스템은 21개 값 가운데 5개가 Tailwind 램프와 같았다.

## 5. 한글 글꼴 후보(Noto Sans KR·Pretendard 밖)
designer `index.html` 은 외부 리소스를 쓰지 않으므로 글꼴 파일을 `assets/`·시스템 사본에 넣어야 한다. OFL 은 번들·재배포가 되고 글꼴 단독 판매만 막는다.
| 글꼴 | 성격 | 라이선스 | 출처 |
|---|---|---|---|
| SUIT / SUITE | 단정한 네오 그로테스크, 9굵기·가변 | OFL-1.1 | github.com/sun-typeface/SUIT |
| Wanted Sans | 가변, 라틴 품질 좋음 | OFL-1.1 | github.com/wanteddev/wanted-sans |
| Spoqa Han Sans Neo | 담백, 작은 글자 가독성 | OFL-1.1 | github.com/spoqa/spoqa-han-sans |
| IBM Plex Sans KR | 기술적·휴머니스트, 7굵기 | OFL-1.1 | github.com/IBM/plex, Google Fonts |
| Asta Sans | 42dot, 가변 wght | OFL(Google Fonts) | fonts.google.com |
| Gothic A1 | 9굵기 고딕 | OFL(Google Fonts) | fonts.google.com |
| LINE Seed Sans KR | 둥근 기하 | OFL 로 알려짐(불확실) | seed.line.me |
| NanumSquare Neo | 네모꼴, 가변 | 네이버 글꼴 라이선스·OFL 표기(산돌구름 안내 기준, 원문 확인 필요) | hangeul.naver.com |
| Gmarket Sans | 굵은 기하 디스플레이 | 산돌구름이 OFL 로 안내(G마켓 원문 확인 필요) | sandollcloud.com/free-font/15744 |
| Paperlogy(페이퍼로지) | 9굵기, 제목·본문 | 산돌구름이 OFL 로 안내(원문 확인 필요) | sandollcloud.com/free-font/21071 |
| MaruBuri(마루 부리) | 본문용 부리(세리프) | 네이버 글꼴 라이선스(OFL 계열, 확인 필요) | hangeul.naver.com |
| Hahmlet | 가변 부리, 제목 | OFL(Google Fonts) | fonts.google.com |
| Gowun Batang / Gowun Dodum | 손맛 있는 바탕·돋움 | OFL(Google Fonts) | fonts.google.com |
| Noto Serif KR, Nanum Myeongjo, Song Myung | 부리 | OFL | fonts.google.com |
| Orbit, Diphylleia, Gasoek One, Bagel Fat One, Black Han Sans, Do Hyeon, Jua | 표시용(제목·로고) | OFL(Google Fonts) | fonts.google.com |
| Galmuri | 픽셀 | OFL-1.1 | github.com/quiple/galmuri |
| KoPubWorld, RIDIBatang, 카페24·에스코어 드림 등 | 본문·제목 | 자체 라이선스(재배포 조건 확인 필요) | 각 배포처 |
- Google Fonts 메타데이터(`fonts.google.com/metadata/fonts`)에서 `korean` 부분집합 패밀리는 38개다. 기계로 고를 후보 목록의 출처로 쓸 수 있다.
- 과용(근거 요구) 목록: Noto Sans KR(본고딕), Pretendard, 시스템 스택(Apple SD Gothic Neo, Malgun Gothic, `system-ui`), Nanum Gothic. 라틴은 impeccable `overused-font`(Inter, Roboto, Fraunces, Geist, Plus Jakarta Sans, Space Grotesk)를 쓴다.
- 다양성 장치: 한글 글꼴은 라틴 글리프도 품는다. `font-family: "<라틴 글꼴>", "<한글 글꼴>"` 순서나 `unicode-range` 로 라틴·숫자에 다른 성격을 줄 수 있다. 부리(세리프) 본문과 돋움 제목처럼 분류를 바꾸는 것도 큰 차이를 만든다. 한글 기울임 금지(§4.7)는 그대로 둔다.

## 6. 레이아웃 다양성(짧게)
- Anthropic: 계획 단계에서 ASCII 와이어프레임으로 레이아웃 개념을 견주고 정렬 방침(왼쪽·가운데)을 정한다.
- Hallmark `references/macrostructures/`(bento-grid 등)와 taste-skill `assets/layout/deal.mjs`(히어로 배정+`layout-history.json`)는 레이아웃도 배정·회전한다.
- impeccable "Refuse"·Anthropic 군집 4·5는 카드 키트와 템플릿 크롬을 금지 쪽으로 정리한다. design-rules §1.4–§1.6 과 겹치고, 빠진 것은 eyebrow·가운뎃점 메타·'→' 버튼·근흑 #111·작은 고정폭 라벨이다.

## 7. 한국어 문구 AI 티 자료(text-rules.md 밖)
- NomaDamas/k-skill `korean-humanizer/references/ai-tell-taxonomy.md`(MIT, 8.4k★, im-not-ai 방법론 계승). text-rules 에 없는 것:
  - 번역투: A-5 "~와 관련하여", A-6 명사화·"~에 기반하여", A-7 "가지고 있다", A-9 "~에 의해" 피동, A-10 "~할 수 있다" 남발, A-11 "~을 위해" 남발, A-16 대명사 직역, A-18 3어절 넘는 좌향 수식, A-19 "~에서의/~으로의" 이중 조사
  - 구조·관용구: C-10 콜론 부제 헤딩 "X: Y" 반복, D-2 "시사하는 바가 크다/주목할 만하다", D-6 결말 공식 "~할 때다/지금이야말로", D-7 "X에서 Y로" 반복, D-8 과장된 의의(이정표·새 지평), D-9 출처 없는 권위("전문가들은")
  - 리듬·수식·장식: E-2 같은 종결 4문장 연속, F-1 동의어 돌려쓰기, F-4·F-5 "-적/-성/-화" 사슬, J-2 줄표(—) 남발
- DaleSeo/korean-skills `humanizer`(MIT, 253★): KatFishNet(arXiv 2503.00032)을 근거로 든다. "쉼표 61% vs 인간 26%"는 스킬 문서의 인용이고 원 논문은 확인하지 않았다(불확실).
- blader/humanizer(MIT, 69k★): 영어 문구용. 위키백과 "Signs of AI writing" 기반이다(위키 본문은 CC BY-SA 라 그대로 옮기지 않는다).
- 국립국어원: 소식지 2022년 7월호 "번역 투 표현을 고쳐써요!", 2026년 2월 "개선이 필요한 공공언어 30선". 목록 원문은 확인하지 못했다(불확실).
- 토스 UX 라이팅: 해요체 통일은 기사로 확인했다. "8가지 원칙" 원문은 찾지 못했다(불확실).
- UI 특화 후보(herdr-team 제안, 외부 출처 없음):
  - 2인칭 "당신(의)" 직역. 생략하거나 voice.md 호칭을 쓴다.
  - 마케팅 상투어: "한눈에", "손쉽게", "간편하게", "스마트한", "새로운 경험", "여정", "솔루션", "올인원", "차원이 다른", "~의 모든 것", "지금 바로 시작하세요"
  - 빈 화면·안내의 "~할 수 있어요" 반복(A-10 의 UI 판)
  - 느낌표 남발

## 8. herdr-team 적용 제안
### 8.1 팔레트 다양성: 추천 방식("배정 → 근거 → 기록")
1. **배정(deal).** 디렉터는 단계 ② 시작에 hue 를 고르지 않고 배정받는다. 새 CLI 를 둔다면 `hteam palette deal --task T-xxx`(표준 라이브러리, 결정적). CLI 가 없으면 같은 절차를 손으로 하고 `deal: manual` 로 적는다.
   - 시드 = SHA-256(`<프로젝트 폴더 이름>:<태스크 ID>:<방향 전환 회차>`). 세부 수정 라운드는 시드를 바꾸지 않고, 방향 전환은 회차를 올린다.
   - OKLCH hue 12구간(30°). 구간 가중치는 impeccable 처럼 "1/카탈로그 항목 수"로 고르게 둔다. 250–300° 구간은 가중치를 낮추고 interview 근거가 없으면 뽑지 않는다.
   - A·B·C 는 서로 원형 거리 60° 이상인 세 구간을 받는다. 무채색 주도 안("먹과 순백, 강조 최소")은 셋 중 하나까지 둔다.
   - 구간마다 카탈로그(§8.3)에서 업종 태그가 맞는 항목 하나를 시드로 고른다. 출처 id(예: `taste:clay-pine`, `impeccable:seed-000`, `metbrewer:Hokusai2`, `wada:#212`)를 붙인다.
2. **근거.** 안마다 무드 문장 하나를 쓴다(impeccable: "1970s travel poster — sun-baked warmth" 처럼 구체적으로. "모던하고 깔끔한"은 안 된다). 서비스의 소재·사용 장면과 어떻게 이어지는지도 쓴다. 주색 hue 는 시드 ±10° 안에 두고 L·C 는 무드로 정한다.
3. **우선순위.** 사용자 브랜드 자산·interview 레퍼런스·직접 쓴 답은 배정보다 앞선다(Anthropic·impeccable "the brief wins"). 그때는 배정 결과를 B·C 에만 쓴다.
4. **기록.** `docs/design/direction.md` 에 `## 팔레트 배정` 을 둔다(시드, 받은 구간, 안별 출처 id, 무드 문장, 근거). 확정 시스템 README 에 `palette_source:` 줄을 둔다.
5. **(선택) 프로젝트 간 회전.** `${XDG_CACHE_HOME:-$HOME/.cache}/herdr-team/palette-history.json` 에 확정 주색 hue 를 남기고, 최근 5개와 ±20° 안이면 다시 배정한다(taste-skill·Hallmark 기록 방식). 캐시 경로는 director 레퍼런스 캡처와 같은 관례다. 개인 경로 사용 규칙과 맞는지는 메인이 판단한다.

### 8.2 파일별 제안
| 파일·절 | 제안 |
|---|---|
| `roles/director.md` 도구 표(18행) | 보드·시안 quickstart 에 `design_systems: false` 를 넣는다(designer 와 같게). 프로젝트 시스템이 아직 없으므로 계정 기본 시스템을 잇지 않는다 |
| `director.md` 단계 ① 3·5(47–50행) | 묶음 예시 "차분한 모노톤·넓은 여백 (추천)" 을 `<묶음 이름>` 자리표시로 바꾸거나, 예시 아래 "예시 문구를 그대로 쓰지 않는다"를 둔다. 묶음 하나는 "이 분야가 늘 내는 모습과 그 반대"를 피한 것이어야 한다(Hallmark set-aside) |
| `director.md` 단계 ② 1번 | "둘 이상 다르게"에 색 조건을 더한다: 주 강조 hue 가 서로 60° 이상, 한글 본문 글꼴이 셋 다 같지 않다, 중립(순회색·틴트)의 선택을 안마다 적는다. 8.1 배정 절차와 Anthropic 자기검토("비슷한 다른 서비스로 같은 프롬프트를 냈을 때 같은 안이 나오면 그 부분을 고친다")를 넣는다 |
| `director.md` 톤 질문 예시(65행) | B 종이(따뜻한 회백+세리프+벽돌색)는 Anthropic 군집 1과 같다. 표 형식만 남기고 값은 `<배경>`·`<강조>` 자리표시로 바꾼다 |
| `director.md` 단계 ③ 1번·질문 예시(95행) | 색 토큰: 강조 램프는 OKLCH 로 만들고(Leonardo 처럼 목표 대비비로 단계를 정한다), Tailwind·Bootstrap 램프 값을 복사하지 않는다. 중립은 Radix natural pairing 처럼 강조 hue 쪽 틴트나 순회색 중 하나를 이유와 함께 고른다. 예시의 `#1F6F5C, Pretendard` 는 자리표시로 바꾼다 |
| `design-rules.md` §1 | 11번: 기본 팔레트·과용 강조(§4 목록, Tailwind·Bootstrap·Material 기본 램프 값)를 근거 없이 쓰지 않는다. 12번: 분야 반사 색(소프트웨어=파랑, 건강=초록, 금융=남색)과 분야 반사 명암(다크=AI·개발 도구)을 근거 없이 쓰지 않는다. 13번: Anthropic 군집의 템플릿 크롬(제목 위 대문자 eyebrow, 가운뎃점 메타, 버튼 끝 '→', 근흑 #111 대용, 장식용 고정폭 라벨)과 크림+세리프+테라코타를 근거 없이 쓰지 않는다. §1 은 이미 "근거와 함께 예외" 구조라 정당한 쓰임은 막지 않는다 |
| `design-rules.md` §1.7 | "Inter나 시스템 글꼴 기본값" 에 "Noto Sans KR·Pretendard·Apple SD Gothic Neo·맑은 고딕"을 더해 근거를 요구한다(금지가 아니다) |
| `design-rules.md` §3 | 3.1 에 중립 선택(순회색·강조 hue 틴트)과 이유를 더한다. 새 8번: 색 면 위 보조 글자·테두리는 그 면의 hue 에서 뽑는다(impeccable `gray-on-color`, Vercel "Hue consistency"). 새 9번: 시스템 README 에 팔레트 출처와 OKLCH 값을 적는다 |
| `design-rules.md` §4 | 새 11번: 한글 글꼴은 §5 후보(라이선스 확인)에서 고르고 고른 이유를 적는다. 라틴·숫자에 다른 글꼴을 짝지을 때는 `font-family` 순서나 `unicode-range` 를 쓴다 |
| `design-rules.md` 출처 절 | 들여온 규칙·데이터마다 출처를 적는다: Anthropic frontend-design(Apache-2.0), impeccable(Apache-2.0, NOTICE), taste-skill(MIT), Hallmark(MIT), Radix(MIT) |
| `review-design.md` 2번(director) | 점검을 더한다: `## 팔레트 배정` 기록, A·B·C hue 거리, 주색이 §4 목록·250–300° 대역이면 근거, 한글 본문 글꼴 근거, 시스템 README 의 `palette_source:` 줄. 위반은 §1 이므로 기존 등급(P1, 근거 있으면 예외)을 따른다 |
| `lib/hteam/lint.py` | 새 검사(모두 경고, 판정은 리뷰어): (a) 과용 강조 hex 정확 일치. (b) `docs/design/system/tokens.json`·CSS 변수의 primary·accent·brand 이름 토큰이 OKLCH h 250–300°, C ≥ 0.08. (c) Tailwind v3 기본 램프 hex 일치 개수(파일당 한 줄). (d) `font-family` 첫 항목이 과용 목록. OKLCH 변환은 표준 라이브러리 공식(OKLab 행렬)으로 하고 기존 `_oklch_family` 와 같은 대역 기준을 쓴다. HSL 기준 `hue_family`(190–300°)는 그라디언트 검사에만 남긴다 |
| `lib/hteam/designdiff.py` | 지운 줄 신호에 "토큰 파일에서 브랜드 강조를 기본 팔레트 값으로 바꿈"을 더할지 검토한다(가치가 낮으면 넣지 않는다) |
| `templates/text-rules.md` §4 | "반복될 때만"에 A-10 "~할 수 있다", A-7 "가지고 있다", A-9 "~에 의해", A-19 "~에서의/~으로의"를 더한다. "항상 고친다"에 D-2·D-6·D-8 과 UI 상투어(§7), 2인칭 "당신"을 더한다. 출처에 k-skill(MIT)을 더한다 |
| `lib/hteam/textlint.py` | 정규식으로 잡히는 것만 더한다: "가지고 있", "에 의해", "에서의|으로의|에의", "시사하는 바|주목할 만하", "한눈에|손쉽게|간편하게|올인원|차원이 다른", "당신의?". 과교정 가드는 text-rules "고치지 않는다" 를 따른다 |

### 8.3 들여올 카탈로그(제안)
- 위치 후보: `herdr-team/lib/hteam/data/palettes.json`(CLI 가 읽는다)과 `templates/` 의 사람용 요약.
- 구성: taste-skill `palettes.json` 64개(MIT, 원 id 유지), impeccable 시드 128개(Apache-2.0, NOTICE 와 변경 고지), MetBrewer 팔레트(CC0), Radix 회색 6종(MIT).
- 항목 필드: `id`, `source`, `license`, `bg/ink/accent`(또는 시드 OKLCH), `mood`, `trades`, `hue_bucket`.
- 빼는 것: nice-color-palettes 데이터(ColourLovers NC 의심), Huemint, Coolors·Color Hunt·Adobe Color 수집, Pantone, 라이선스 불명 전통색 hex.
- Wada 조합은 권리 확인 뒤 선택으로 둔다.

### 8.4 우선순위
1. 비용이 작고 효과가 바로 나는 것: director.md 예시 자리표시화, quickstart `design_systems: false`, ② 의 hue 거리·글꼴 조건과 자기검토 문장.
2. design-rules §1 11–13번, §1.7 한글 과용 글꼴, §3 중립 선택·출처 줄. review-design 점검을 더한다.
3. lint (a)(b)(d), textlint 정규식 몇 개.
4. `hteam palette deal` 과 카탈로그 들여오기(설계 문서와 Codex 리뷰가 필요한 규모). 프로젝트 간 회전 기록은 선택.
