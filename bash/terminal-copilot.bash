# terminal-copilot bash integration
# Bash cannot render native zsh-style ghost text. This records commands and provides Ctrl+F to accept one prediction.

[ -n "$BASH_VERSION" ] || return 0

: ${TERM_COPILOT_HOST:=127.0.0.1}
: ${TERM_COPILOT_PORT:=8765}
: ${TERM_COPILOT_URL:=http://${TERM_COPILOT_HOST}:${TERM_COPILOT_PORT}}

__term_copilot_is_root_mode() {
  [ "${TERM_COPILOT_ROOT_MODE:-}" = "1" ] || [ "${EUID:-}" = "0" ]
}

__term_copilot_post_json() {
  local endpoint="$1" payload="$2"
  TERM_COPILOT_ENDPOINT="$endpoint" TERM_COPILOT_PAYLOAD="$payload" python3 - <<'PY' >/dev/null 2>&1 &
import os, urllib.request
url = os.environ.get("TERM_COPILOT_URL", "http://127.0.0.1:8765") + os.environ["TERM_COPILOT_ENDPOINT"]
req = urllib.request.Request(url, data=os.environ["TERM_COPILOT_PAYLOAD"].encode(), headers={"Content-Type":"application/json"})
try:
    urllib.request.urlopen(req, timeout=0.25).read()
except Exception:
    pass
PY
}

__term_copilot_predict_json() {
  TERM_COPILOT_BUFFER="$1" TERM_COPILOT_CURSOR="$2" TERM_COPILOT_CWD="$PWD" python3 - <<'PY' 2>/dev/null
import json, os

def int_or_none(value):
    try:
        return int(value)
    except Exception:
        return None

effective_uid = os.geteuid() if hasattr(os, "geteuid") else int_or_none(os.environ.get("EUID"))
payload = {
  "protocol_version": 1,
  "buffer": os.environ.get("TERM_COPILOT_BUFFER", ""),
  "cursor": int_or_none(os.environ.get("TERM_COPILOT_CURSOR")) or 0,
  "cwd": os.environ.get("TERM_COPILOT_CWD"),
  "shell": "bash",
  "user": os.environ.get("USER"),
  "effective_uid": effective_uid,
  "original_user": os.environ.get("SUDO_USER") or os.environ.get("TERM_COPILOT_USER"),
  "term_copilot_home": os.environ.get("TERM_COPILOT_HOME"),
  "root_mode": os.environ.get("TERM_COPILOT_ROOT_MODE") == "1" or effective_uid == 0,
}
print(json.dumps(payload, ensure_ascii=False), end="")
PY
}

__term_copilot_json_event() {
  TERM_COPILOT_EVENT="$1" TERM_COPILOT_COMMAND="$2" TERM_COPILOT_EXIT_CODE="$3" TERM_COPILOT_CWD="$PWD" python3 - <<'PY' 2>/dev/null
import json, os
payload = {
  "event": os.environ.get("TERM_COPILOT_EVENT"),
  "command": os.environ.get("TERM_COPILOT_COMMAND") or None,
  "cwd": os.environ.get("TERM_COPILOT_CWD"),
  "shell": "bash",
  "exit_code": int(os.environ.get("TERM_COPILOT_EXIT_CODE") or 0),
}
print(json.dumps(payload, ensure_ascii=False), end="")
PY
}

__term_copilot_prompt_command() {
  local exit_code="$?"
  local cmd
  cmd="$(history 1 | sed 's/^ *[0-9]* *//')"
  [ -n "$cmd" ] && __term_copilot_post_json "/events" "$(__term_copilot_json_event command_executed "$cmd" "$exit_code")"
}

case ";$PROMPT_COMMAND;" in
  *";__term_copilot_prompt_command;"*) ;;
  *) PROMPT_COMMAND="__term_copilot_prompt_command${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac

term_copilot_bash_accept() {
  local payload response full
  payload="$(__term_copilot_predict_json "$READLINE_LINE" "$READLINE_POINT")"
  response="$(TERM_COPILOT_PAYLOAD="$payload" python3 - <<'PY' 2>/dev/null
import json, os, socket, urllib.request

payload = os.environ.get("TERM_COPILOT_PAYLOAD", "{}")
try:
    parsed = json.loads(payload)
except Exception:
    parsed = {}
root_mode = bool(parsed.get("root_mode"))
socket_path = os.environ.get("TERM_COPILOT_SOCKET") or ""
timeout = float(os.environ.get("TERM_COPILOT_TIMEOUT", "0.45"))

if socket_path and os.path.exists(socket_path) and hasattr(socket, "AF_UNIX"):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(socket_path)
            client.sendall(payload.encode("utf-8") + b"\n")
            chunks = []
            while True:
                chunk = client.recv(8192)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            print(b"".join(chunks).split(b"\n", 1)[0].decode("utf-8"), end="")
            raise SystemExit
    except Exception:
        pass

if root_mode:
    raise SystemExit

url = os.environ.get("TERM_COPILOT_URL", "http://127.0.0.1:8765") + "/predict"
req = urllib.request.Request(url, data=payload.encode(), headers={"Content-Type":"application/json"})
try:
    print(urllib.request.urlopen(req, timeout=timeout).read().decode(), end="")
except Exception:
    pass
PY
)"
  full="$(TERM_COPILOT_RESPONSE="$response" python3 - <<'PY' 2>/dev/null
import json, os
try:
  print(json.loads(os.environ.get("TERM_COPILOT_RESPONSE", "{}" )).get("full_command", ""), end="")
except Exception:
  pass
PY
)"
  if [ -n "$full" ]; then
    READLINE_LINE="$full"
    READLINE_POINT=${#READLINE_LINE}
  fi
}

bind -x '"\C-f": term_copilot_bash_accept' 2>/dev/null || true
