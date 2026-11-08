#!/usr/bin/env bash
# Codex 리뷰를 Herdr pane 에서 돌린다.
# 호출한 터미널과 같은 space 의 "리뷰" 탭에 pane 이 생기고, 리뷰가 끝나면 pane 이 닫힌다.
# 화면은 지금 탭에 머문다. 마지막 리뷰가 끝나면 "리뷰" 탭도 사라진다.
#
# 사용:
#   scripts/codex-review.sh doc <이름> <프롬프트 파일>   문서 리뷰(read-only 샌드박스)
#   scripts/codex-review.sh commit <sha>                 커밋 리뷰
#   scripts/codex-review.sh base <브랜치>                브랜치 전체 리뷰(그 브랜치 대비)
#
# 결과: .codex-reviews/<이름>.md(마지막 메시지), .log(전체 출력), .exit(종료 코드).
# 커밋 리뷰 이름은 commit-<sha 7자>, 브랜치 리뷰는 base-<브랜치>.
# 표준 출력: 만든 터미널 주소 한 줄. 끝날 때까지 기다리려면 `hc wait <주소> --timeout 3600`.
# 모델: 기본 gpt-6.1-sol(사용자 전역 Codex 기본 모델보다 빠르고 사용량이 적다). CODEX_REVIEW_MODEL 로 바꾼다.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
out="$root/.codex-reviews"
model=${CODEX_REVIEW_MODEL:-gpt-6.1-sol}

usage() { sed -n '5,8p' "$0" >&2; exit 2; }

# pane 안에서 도는 부분: 리뷰를 돌리고 로그와 종료 코드를 남긴다.
if [[ "${1:-}" == __run ]]; then
  name=$2
  shift 2
  rm -f "$out/$name.md" "$out/$name.exit"
  set +e
  "$@" </dev/null 2>&1 | tee "$out/$name.log"
  code=${PIPESTATUS[0]}
  echo "$code" >"$out/$name.exit"
  exit "$code"
fi

mode=${1:-}
case "$mode" in
  doc)
    [[ $# -eq 3 ]] || usage
    name=$2
    [[ -f "$3" ]] || { echo "프롬프트 파일이 없다: $3" >&2; exit 2; }
    cmd=(codex exec -m "$model" --sandbox read-only -o "$out/$name.md" "$(cat "$3")")
    ;;
  commit)
    [[ $# -eq 2 ]] || usage
    sha=$(git rev-parse --verify "$2^{commit}")
    name="commit-${sha:0:7}"
    cmd=(codex exec review -m "$model" --commit "$sha" -o "$out/$name.md")
    ;;
  base)
    [[ $# -eq 2 ]] || usage
    git rev-parse --verify --quiet "$2" >/dev/null || { echo "브랜치가 없다: $2" >&2; exit 2; }
    name="base-${2//\//-}"
    cmd=(codex exec review -m "$model" --base "$2" -o "$out/$name.md")
    ;;
  *) usage ;;
esac

[[ -n "${HC_TERMINAL_ID:-}" ]] || { echo "Herdr 터미널 안에서 실행해야 한다(HC_TERMINAL_ID 없음)" >&2; exit 2; }

# 호출한 터미널의 space 를 읽는다. 리뷰는 그 space 의 "리뷰" 탭에 pane 으로 뜬다.
space=$(hc get "$HC_TERMINAL_ID" --json | python3 -c '
import json, sys
print(json.load(sys.stdin)["labels"]["herdr.space"])')

# 리뷰 탭 id 는 space 마다 하나로 정한다. 조회하지 않으므로 창이 닫혀 있어도 되고,
# 동시에 띄워도 같은 탭에 모인다. Herdr 가 모르는 id 는 새 탭이 되고, 닫힌 뒤에도 같은 id 로 다시 생긴다.
tab_name="리뷰"
tab=tb$(printf 'horch-review\n%s' "$space" | shasum | cut -c1-32)

# hc 터미널 이름은 코어 전체에서 유일해야 한다. 접미사는 저장소 경로와 자르기 전 리뷰 이름에서 만든다.
# 다른 worktree 나 다른 리뷰는 함께 돌고, 같은 저장소의 같은 리뷰는 결과 파일이 겹치므로 두 번째가 거부된다.
sfx=$(printf '%s\n%s' "$root" "$name" | shasum | cut -c1-6)
tname=$(printf 'codex-%s' "$name" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9_\n-' '-' | cut -c1-25)-$sfx
mkdir -p "$out"

if ! res=$(hc run --bg --json --no-notify --outlive-parent --rm --cwd "$root" --name "$tname" \
  --label "herdr.space=$space" --label "herdr.tab=$tab" \
  -- "$root/scripts/codex-review.sh" __run "$name" "${cmd[@]}" 2>&1); then
  echo "리뷰를 시작하지 못했다. name_taken 이면 같은 리뷰($name)가 이미 돌고 있다: $res" >&2
  exit 1
fi
# 탭 이름을 붙인다(이미 붙어 있어도 그대로다). 탭이 화면에 생길 때까지 잠깐 다시 시도하고,
# 창이 닫혀 있거나 끝내 안 되면 번호 이름으로 둔다. 리뷰는 이와 상관없이 돈다.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  herdr-app do tab.rename --id "$tab" --name "$tab_name" >/dev/null 2>&1 && break
  sleep 0.3
done
printf '%s' "$res" | python3 -c 'import json, sys; print(json.load(sys.stdin)["address"])'
