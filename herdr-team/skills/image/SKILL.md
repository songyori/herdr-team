---
name: image
description: >
  Codex 내장 image_gen 으로 래스터 이미지(일러스트, 아이콘 비트맵, 배경, 사진풍 이미지)를 만든다. herdr-team 디자인 워커가
  자기 pane 에서 쓴다. 트리거: "/herdr-team:image", "이미지 만들어", "일러스트·아이콘·배경 생성". SVG·CSS·다이어그램처럼
  코드로 그리는 편이 맞는 요청과 화면 전체를 그리는 요청에는 쓰지 않는다.
argument-hint: "[--n <1..8>] [--out <폴더>] [--ar <w:h>] [--transparent] [--ref <파일>]... [--background] <프롬프트>"
---

# /herdr-team:image

`.herdr-team/bin/hteam image` 가 이미지마다 `codex exec`(샌드박스 우회, 내장 image_gen)를 한 번 부르고 검사한 PNG 를 `--out` 에 새 이름으로 둔다(덮어쓰지 않는다). 만든 이미지는 이 세션(Claude)이 직접 보고 검토한다. 이미지 생성은 직무가 아니고 pane 을 따로 띄우지 않는다.

## 1. 인자
인자: `$ARGUMENTS`

- 문법 `[--flag 값]... <프롬프트>`. `--n <1..8>`(기본 1), `--out <폴더>`(기본 `./generated/`, 화면 에셋이면 태스크 owns 안의 `assets/<화면>/`), `--ar <w:h>`, `--transparent`, `--ref <파일>`(여러 번, 참조·편집 대상), `--background`.
- 모르는 `--` 낱말은 쓰지 않고 멈춘다. 프롬프트가 비었으면 무엇을 그릴지 정한 뒤 다시 한다. `--ref` 파일이 없으면 멈춘다.
- 프롬프트에 비밀값을 넣지 않는다. 프롬프트는 실행 폴더의 `prompt.txt` 와 보고서로 남는다.

## 2. 실행
`--background` 는 hteam 에 넘기지 않는다(아래 실행 방식만 정한다). 프롬프트가 `-` 로 시작할 수 있으므로 `--` 뒤에 둔다.

| 조건 | 방식 |
|---|---|
| `--n` 이 1 이고 `--background` 가 없다 | 포그라운드. Bash `timeout: 600000`, `--timeout 450`(이미지 하나의 시간 제한) |
| `--n` ≥ 2 이거나 `--background` | Bash `run_in_background: true`. `--timeout` 은 주지 않는다(기본 900초). "N장 만드는 중, 끝나면 알림" 한 줄로 알리고 다른 일을 한다 |

포그라운드의 최악 시간이 Bash 최대 600초 안에 든다: 사전 점검 30 + `--timeout` 450 + 래퍼 여유(GRACE) 30 + TERM 뒤 KILL 까지 15 + PNG 변환(sips) 60 = 30 + 450 + 30 + 15 + 60 = 585초. 두 장부터는 이 합이 600초를 넘을 수 있어 백그라운드로 돌린다.

```bash
.herdr-team/bin/hteam image --n 1 --out assets/home --ar 16:9 --timeout 450 -- "따뜻한 오후 햇살이 드는 작업실 일러스트, 평면 스타일"
```

## 3. 결과 읽기
출력은 JSON 한 개다. `images` 의 항목마다 `status` 를 본다.

| status | 할 일 |
|---|---|
| `ok` | `path`·`width`·`height`·`alpha` 를 본다. `--transparent` 면 `transparent` 가 `native`(투명)·`chroma`(배경색을 지웠다)인지 보고, `warnings` 가 있으면 직접 확인한다 |
| `refused` | Codex 가 거절했거나 턴이 실패했다. `result`·`progress` 를 그대로 보고서에 남기고 같은 프롬프트로 다시 하지 않는다(정책 거절일 수 있다). 프롬프트를 바꿀지 판단한다 |
| `failed` | `reason` 을 본다. 시간 초과(exit 10)·진행 신호 없음(11)·래퍼가 끝나지 않음이면 한 번만 다시 해 볼 수 있다. 두 번째도 실패면 멈추고 보고서에 적는다. 결과가 심볼릭 링크이거나 PNG 로 바꾸지 못했으면 다시 하지 않고 보고서에 적는다 |

오류 `image_interrupted` 는 중단됐다는 뜻이다. `images` 에 끝낸 것까지 있다. 남은 수만큼 다시 부를지 정한다. 실행 중에 나온 `codex_missing` 에도 `images` 가 붙는다(그때까지 만든 것).

exit 12(`codex_missing`·`no_image_generation`·`wrapper_missing`)면 이미지를 만들 수 없다. 프리앰블의 ask 명령으로 코디네이터에게 알린다(사용자가 `codex features enable image_generation` 등을 한다). 시험 생성을 하지 않는다(쿼터를 쓴다).

## 4. 검토와 커밋
- 만든 PNG 를 Read 로 하나씩 직접 연다. 요청과 맞는지, 잘린 곳·글자 깨짐·워터마크·AI 티(`.herdr-team/design-rules.md`)가 없는지 본다. "예쁜가" 는 사용자가 일괄 승인에서 본다.
- 채택한 파일만 경로를 지정해 커밋한다(태스크 owns 안). 버린 파일은 지운다.
- 보고서 이번 라운드 절의 `### 이미지` 에 프롬프트, 만든 수, 채택한 파일과 이유, 거절·실패를 적는다.

## 하지 않는 것
- 화면 전체를 이미지로 그리기(화면은 Claude Design 과 화면 원본 `index.html` 로 만든다).
- 거절된 프롬프트를 그대로 다시 하기, 사용자 Codex 설정 고치기.
