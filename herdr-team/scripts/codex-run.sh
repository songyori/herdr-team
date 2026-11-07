#!/usr/bin/env bash
#
# codex-run.sh — codex exec 를 한 번 감시하며 실행한다(설계 12장). hteam image 가 이미지마다 부른다.
#
# 반드시 끝난다: 전체 시간 초과(exit 10)·진행 신호 없음(exit 11)이면 프로세스 그룹째 죽인다. 앞의 `codex --version` 도
# 자기 프로세스 그룹·stdin /dev/null 로 돌리고 HTEAM_CODEX_VERSION_WAIT 초(기본 10) 안에 안 끝나면 그룹째 끝내고 버전 없이
# 간다. 중단(INT·TERM·HUP) trap 은 버전 조회 전에 건다.
# 정책이 없다. 한 번 실행하고 왜 끝났는지 status.json 에 남긴다. 다시 할지는 부르는 쪽이 정한다.
# exit 0 은 "codex 가 정상 종료했다" 이지 "이미지를 만들었다" 가 아니다. 내용은 부르는 쪽이 result.txt 로 본다.
# 턴이 끝났는지는 exit 보다 status.json 의 terminal_event(turn.completed·turn.failed·error)가 먼저다:
# 시간 초과로 죽였어도 terminal_event 가 turn.completed 면 일은 이미 끝났다.
#
# 지키는 것(빼지 않는다):
#   - stdin 은 /dev/null. 열려 있으면 codex exec 가 stdin 의 EOF 를 기다리며 시작하지 못한다.
#   - --json(이벤트 스트림 → events.jsonl, 진행 신호와 terminal_event 의 근거)과 --output-last-message(최종 메시지 →
#     result.txt)는 함께 쓴다.
#   - -C <cwd>. 빠뜨리면 codex 가 부른 셸의 cwd 에서 뜬다.
#   - --dangerously-bypass-approvals-and-sandbox: 비대화 실행이 승인 창에서 멈추지 않고 image_gen 결과 파일을 읽게
#     한다(설계 14장). 프롬프트는 이미지 생성만 시킨다(부르는 쪽 책임).
#   - --skip-git-repo-check. 환경은 그대로 물려준다(자격 증명이 환경에서 온다).
#
# bash 3.2(macOS 기본) 호환. jq·GNU timeout 을 쓰지 않는다.

set -u

usage() {
  cat >&2 <<'USAGE'
사용법:
  codex-run.sh --profile image --prompt-file <파일> --run-dir <폴더>
               [--cwd <폴더>] [--model <모델>] [--effort <effort>] [--image <파일>]...
               [--codex-arg=<인자>]... [--timeout <초>] [--heartbeat <초>]

  --profile    image(시간 제한 900초, 진행 신호 없음 한도 300초)
  --cwd        codex 의 작업 루트(-C). 기본은 지금 폴더
  --model      없으면 사용자 Codex 설정을 따른다
  --effort     -c model_reasoning_effort=<값> 으로 넘긴다
  --image      프롬프트에 붙일 참조 이미지(-i). 여러 번 쓸 수 있다
  --codex-arg  codex exec 에 그대로 붙일 인자([agents.codex].args). 여러 번 쓸 수 있다

exit: 0 정상 종료, 10 시간 초과, 11 진행 신호 없음, 12 codex 없음, 1 그 밖의 비정상 종료,
      2 인자 오류(status.json 을 만들지 않는다), 130 중단
USAGE
}

PROFILE=""; CWD=""; MODEL=""; EFFORT=""; PROMPT_FILE=""; RUN_DIR=""; TIMEOUT=""; HEARTBEAT=""
IMAGES=()
EXTRA=()

need_val() {  # $1=플래그 $2=남은 인자 수. bash 3.2 의 shift 2 는 값이 없으면 시프트하지 않아 루프가 끝나지 않는다
  if [ "$2" -lt 2 ]; then
    echo "인자 값 누락: $1" >&2
    usage
    exit 2
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --profile)     need_val "$1" "$#"; PROFILE="$2";     shift 2 ;;
    --cwd)         need_val "$1" "$#"; CWD="$2";         shift 2 ;;
    --model)       need_val "$1" "$#"; MODEL="$2";       shift 2 ;;
    --effort)      need_val "$1" "$#"; EFFORT="$2";      shift 2 ;;
    --image)       need_val "$1" "$#"; IMAGES[${#IMAGES[@]}]="$2"; shift 2 ;;
    --codex-arg=*) EXTRA[${#EXTRA[@]}]="${1#--codex-arg=}"; shift ;;
    --prompt-file) need_val "$1" "$#"; PROMPT_FILE="$2"; shift 2 ;;
    --run-dir)     need_val "$1" "$#"; RUN_DIR="$2";     shift 2 ;;
    --timeout)     need_val "$1" "$#"; TIMEOUT="$2";     shift 2 ;;
    --heartbeat)   need_val "$1" "$#"; HEARTBEAT="$2";   shift 2 ;;
    -h|--help)     usage; exit 2 ;;
    *) echo "알 수 없는 인자: $1" >&2; usage; exit 2 ;;
  esac
done

for pair in "profile:$PROFILE" "prompt-file:$PROMPT_FILE" "run-dir:$RUN_DIR"; do
  if [ -z "${pair#*:}" ]; then
    echo "필수 인자 누락: --${pair%%:*}" >&2
    usage
    exit 2
  fi
done

case "$PROFILE" in
  image) : "${TIMEOUT:=900}"; : "${HEARTBEAT:=300}" ;;
  *) echo "--profile 은 image 다: $PROFILE" >&2; usage; exit 2 ;;
esac

if [ ! -f "$PROMPT_FILE" ] || [ ! -r "$PROMPT_FILE" ] || [ ! -s "$PROMPT_FILE" ]; then
  echo "프롬프트 파일이 없거나 비었거나 읽을 수 없다: $PROMPT_FILE" >&2
  exit 2
fi
for img in ${IMAGES[@]+"${IMAGES[@]}"}; do
  if [ ! -f "$img" ] || [ ! -r "$img" ] || [ ! -s "$img" ]; then
    echo "참조 이미지가 없거나 비었거나 읽을 수 없다: $img" >&2
    exit 2
  fi
done

is_uint() {  # 0 이상 9자리 이하 정수. 아니면 [ -lt ] 비교가 오류(rc=2)로 늘 거짓이 되어 시간 제한이 듣지 않는다
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    ??????????*) return 1 ;;
    *) return 0 ;;
  esac
}
for pair in "timeout:$TIMEOUT" "heartbeat:$HEARTBEAT"; do
  if ! is_uint "${pair#*:}"; then
    echo "--${pair%%:*} 는 9자리 이하의 0 이상 정수다: ${pair#*:}" >&2
    exit 2
  fi
done
if [ "$HEARTBEAT" -ge "$TIMEOUT" ]; then  # 같거나 크면 전체 시간 초과가 늘 먼저라 진행 신호 감시가 듣지 않는다
  echo "--heartbeat(${HEARTBEAT}초)는 --timeout(${TIMEOUT}초)보다 작아야 한다" >&2
  exit 2
fi

: "${CWD:=$PWD}"
CWD="$(cd "$CWD" 2>/dev/null && pwd -P)" || { echo "--cwd 로 이동할 수 없다" >&2; exit 2; }
mkdir -p "$RUN_DIR" || { echo "run-dir 을 만들 수 없다: $RUN_DIR" >&2; exit 2; }

RESULT="$RUN_DIR/result.txt"
EVENTS="$RUN_DIR/events.jsonl"
PROGRESS="$RUN_DIR/progress.log"
STATUS="$RUN_DIR/status.json"

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }
json_str() { printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"; }

STARTED_AT="$(now_iso)"
LAST_EVENT_AT="$STARTED_AT"
CODEX_PID=""
VERSION_PID=""
TERMINAL_EVENT=null
SILENCE=0
CODEX_VERSION=null
CWD_JSON="$(json_str "$CWD")"

scan_terminal() {  # 마지막 종단 이벤트. codex 의 JSONL 은 공백 없는 compact 줄이라 줄 머리로 가른다
  TERMINAL_EVENT=null
  [ -s "$EVENTS" ] || return 0
  T="$(grep -oE '^\{"type":"(turn\.completed|turn\.failed|error)"' "$EVENTS" 2>/dev/null | tail -1 | sed 's/^{"type"://')"
  [ -n "$T" ] && TERMINAL_EVENT="$T"
  return 0
}

write_status() {  # $1=state $2=raw_exit(숫자|null) $3=exit(숫자|null). 임시 파일 + mv 로 원자적으로 쓴다
  printf '{\n  "profile": "%s",\n  "state": "%s",\n  "pid": %s,\n  "cwd": %s,\n  "codex_version": %s,\n  "started_at": "%s",\n  "last_event_at": "%s",\n  "silence_secs": %s,\n  "terminal_event": %s,\n  "raw_exit": %s,\n  "exit": %s\n}\n' \
    "$PROFILE" "$1" "${CODEX_PID:-null}" "$CWD_JSON" "$CODEX_VERSION" "$STARTED_AT" "$LAST_EVENT_AT" "$SILENCE" \
    "$TERMINAL_EVENT" "$2" "$3" > "$STATUS.tmp.$$" && mv -f "$STATUS.tmp.$$" "$STATUS"
}

: > "$RESULT"
: > "$EVENTS"
: > "$PROGRESS"

if ! command -v codex >/dev/null 2>&1; then
  write_status missing null 12
  echo "codex 가 PATH 에 없다. hteam doctor 를 돌린다" >&2
  exit 12
fi
stop_group() {  # $1=pid. 그 프로세스 그룹째(자식까지) 끝낸다: TERM, 5초 안에 안 끝나면 KILL
  [ -n "$1" ] || return 0
  kill -TERM "-$1" 2>/dev/null || kill -TERM "$1" 2>/dev/null
  i=0
  while [ "$i" -lt 5 ] && kill -0 "$1" 2>/dev/null; do
    sleep 1
    i=$((i+1))
  done
  kill -KILL "-$1" 2>/dev/null || kill -KILL "$1" 2>/dev/null
  return 0
}
kill_group() { stop_group "$VERSION_PID"; stop_group "$CODEX_PID"; }
trap 'kill_group; scan_terminal; write_status failed null 130; exit 130' INT TERM HUP

VERSION_WAIT="${HTEAM_CODEX_VERSION_WAIT:-10}"
is_uint "$VERSION_WAIT" || VERSION_WAIT=10
VERSION_OUT="$RUN_DIR/version.txt"
set -m
( exec codex --version ) >"$VERSION_OUT" 2>/dev/null </dev/null &
VERSION_PID=$!
set +m
i=0
while kill -0 "$VERSION_PID" 2>/dev/null && [ "$i" -lt $((VERSION_WAIT * 5)) ]; do
  sleep 0.2
  i=$((i+1))
done
if kill -0 "$VERSION_PID" 2>/dev/null; then
  echo "codex --version 이 ${VERSION_WAIT}초 안에 끝나지 않아 버전 없이 진행한다" >&2
  stop_group "$VERSION_PID"
fi
wait "$VERSION_PID" 2>/dev/null
VERSION_PID=""
V="$(head -1 "$VERSION_OUT" 2>/dev/null | tr -d '\r')"
rm -f "$VERSION_OUT"
[ -n "$V" ] && CODEX_VERSION="$(json_str "$V")"

PROMPT="$(cat "$PROMPT_FILE")"

set --  # 선택 인자는 있을 때만. bash 3.2 의 빈 배열 확장이 set -u 와 부딪치므로 위치 인자에 쌓는다
for a in ${EXTRA[@]+"${EXTRA[@]}"}; do set -- "$@" "$a"; done
[ -n "$MODEL" ]  && set -- "$@" --model "$MODEL"
[ -n "$EFFORT" ] && set -- "$@" -c "model_reasoning_effort=$EFFORT"
for img in ${IMAGES[@]+"${IMAGES[@]}"}; do set -- "$@" -i "$img"; done  # -i 는 값을 여럿 받으므로 --json 앞에 둔다

set -m  # codex 에 자기 프로세스 그룹을 준다(pgid == $!)
(
  exec codex exec \
    --skip-git-repo-check \
    --dangerously-bypass-approvals-and-sandbox \
    -C "$CWD" \
    "$@" \
    --json \
    --output-last-message "$RESULT" \
    "$PROMPT"
) >"$EVENTS" 2>"$PROGRESS" </dev/null &
CODEX_PID=$!
set +m
write_status running null null

START_TS="$(date +%s)"
LAST_EVENT_TS="$START_TS"
LAST_SIZE=0
while kill -0 "$CODEX_PID" 2>/dev/null; do
  sleep 1  # 1초마다 본다(이미지 한 장은 수십 초–몇 분이라 비용이 작다)
  kill -0 "$CODEX_PID" 2>/dev/null || break  # 자는 사이 끝났으면 시간 초과로 보지 않는다
  NOW_TS="$(date +%s)"
  # 진행 신호는 두 스트림 크기의 합이다(--json 이면 진행 글은 거의 stdout 으로 간다)
  SIZE_E="$(wc -c < "$EVENTS" 2>/dev/null | tr -d ' ')"; [ -n "$SIZE_E" ] || SIZE_E=0
  SIZE_P="$(wc -c < "$PROGRESS" 2>/dev/null | tr -d ' ')"; [ -n "$SIZE_P" ] || SIZE_P=0
  SIZE=$((SIZE_E + SIZE_P))
  if [ "$SIZE" -ne "$LAST_SIZE" ]; then
    LAST_SIZE="$SIZE"
    LAST_EVENT_TS="$NOW_TS"
    LAST_EVENT_AT="$(now_iso)"
  fi
  SILENCE=$((NOW_TS - LAST_EVENT_TS))
  write_status running null null
  if [ $((NOW_TS - START_TS)) -ge "$TIMEOUT" ]; then
    kill_group
    scan_terminal
    write_status timeout null 10
    echo "전체 시간 ${TIMEOUT}초를 넘겨 끝냈다(terminal_event=${TERMINAL_EVENT})" >&2
    exit 10
  fi
  if [ "$SILENCE" -ge "$HEARTBEAT" ]; then
    kill_group
    scan_terminal
    write_status stalled null 11
    echo "진행 신호가 ${HEARTBEAT}초 동안 없어 끝냈다(terminal_event=${TERMINAL_EVENT})" >&2
    exit 11
  fi
done

wait "$CODEX_PID"
RAW=$?
scan_terminal
SILENCE=$(( $(date +%s) - LAST_EVENT_TS ))
if [ "$RAW" -eq 0 ]; then
  write_status ok 0 0
  exit 0
fi
write_status failed "$RAW" 1
echo "codex 가 비정상 종료했다(raw_exit=$RAW, terminal_event=${TERMINAL_EVENT}). progress.log 를 본다" >&2
exit 1
