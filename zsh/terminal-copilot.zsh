# terminal-copilot zsh integration
# Requires zsh-autosuggestions for real ghost-text rendering.

[[ -n "$ZSH_VERSION" ]] || return 0

: ${TERM_COPILOT_HOST:=127.0.0.1}
: ${TERM_COPILOT_PORT:=8765}
: ${TERM_COPILOT_URL:=http://${TERM_COPILOT_HOST}:${TERM_COPILOT_PORT}}
: ${TERM_COPILOT_TIMEOUT:=0.45}

zmodload zsh/datetime 2>/dev/null || true

typeset -g TERM_COPILOT_LAST_FULL=""
typeset -g TERM_COPILOT_LAST_BUFFER=""
typeset -g TERM_COPILOT_LAST_SOURCE=""
typeset -g TERM_COPILOT_EXEC_CMD=""
typeset -g TERM_COPILOT_EXEC_STARTED=""

_term_copilot_http_json() {
  local endpoint="$1"
  local payload="$2"
  TERM_COPILOT_ENDPOINT="$endpoint" TERM_COPILOT_PAYLOAD="$payload" python3 - <<'PY' 2>/dev/null
import json
import os
import urllib.request

url = os.environ.get("TERM_COPILOT_URL", "http://127.0.0.1:8765") + os.environ["TERM_COPILOT_ENDPOINT"]
payload = os.environ.get("TERM_COPILOT_PAYLOAD", "{}")
timeout = float(os.environ.get("TERM_COPILOT_TIMEOUT", "0.45"))
try:
    req = urllib.request.Request(url, data=payload.encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        print(response.read().decode("utf-8"), end="")
except Exception:
    pass
PY
}

_term_copilot_predict_json() {
  local prefix="$1"
  local cursor="$2"
  TERM_COPILOT_BUFFER="$prefix" TERM_COPILOT_CURSOR="$cursor" TERM_COPILOT_CWD="$PWD" python3 - <<'PY' 2>/dev/null
import json
import os
payload = {
    "buffer": os.environ.get("TERM_COPILOT_BUFFER", ""),
    "cursor": int(os.environ.get("TERM_COPILOT_CURSOR", "0") or 0),
    "cwd": os.environ.get("TERM_COPILOT_CWD"),
    "shell": "zsh",
    "user": os.environ.get("USER"),
    "effective_uid": os.geteuid() if hasattr(os, "geteuid") else None,
    "original_user": os.environ.get("SUDO_USER") or os.environ.get("TERM_COPILOT_USER"),
    "root_mode": os.environ.get("TERM_COPILOT_ROOT_MODE") == "1",
}
print(json.dumps(payload, ensure_ascii=False), end="")
PY
}

_term_copilot_event_json() {
  local event="$1" command="$2" exit_code="$3" duration_ms="$4" suggestion="$5" source="$6"
  TERM_COPILOT_EVENT="$event" TERM_COPILOT_COMMAND="$command" TERM_COPILOT_EXIT_CODE="$exit_code" TERM_COPILOT_DURATION_MS="$duration_ms" TERM_COPILOT_SUGGESTION="$suggestion" TERM_COPILOT_SOURCE="$source" TERM_COPILOT_CWD="$PWD" python3 - <<'PY' 2>/dev/null
import json
import os

def int_or_none(value):
    try:
        return int(value)
    except Exception:
        return None
payload = {
    "event": os.environ.get("TERM_COPILOT_EVENT"),
    "command": os.environ.get("TERM_COPILOT_COMMAND") or None,
    "buffer": os.environ.get("TERM_COPILOT_BUFFER") or None,
    "suggestion": os.environ.get("TERM_COPILOT_SUGGESTION") or None,
    "source": os.environ.get("TERM_COPILOT_SOURCE") or None,
    "cwd": os.environ.get("TERM_COPILOT_CWD"),
    "shell": "zsh",
    "exit_code": int_or_none(os.environ.get("TERM_COPILOT_EXIT_CODE")),
    "duration_ms": int_or_none(os.environ.get("TERM_COPILOT_DURATION_MS")),
}
print(json.dumps(payload, ensure_ascii=False), end="")
PY
}

_term_copilot_post_event() {
  local event="$1" command="$2" exit_code="$3" duration_ms="$4" suggestion="$5" source="$6"
  local payload
  payload="$(_term_copilot_event_json "$event" "$command" "$exit_code" "$duration_ms" "$suggestion" "$source")"
  [[ -n "$payload" ]] && { TERM_COPILOT_PAYLOAD="$payload" TERM_COPILOT_ENDPOINT="/events" python3 - <<'PY' >/dev/null 2>&1 &!
import os, urllib.request
url = os.environ.get("TERM_COPILOT_URL", "http://127.0.0.1:8765") + os.environ["TERM_COPILOT_ENDPOINT"]
req = urllib.request.Request(url, data=os.environ["TERM_COPILOT_PAYLOAD"].encode(), headers={"Content-Type":"application/json"})
try:
    urllib.request.urlopen(req, timeout=0.25).read()
except Exception:
    pass
PY
  }
}

_zsh_autosuggest_strategy_term_copilot() {
  local prefix="$1"
  [[ -z "$prefix" ]] && return
  [[ ${#prefix} -lt 2 ]] && return

  local payload response ghost full source
  payload="$(_term_copilot_predict_json "$prefix" "${#prefix}")"
  response="$(_term_copilot_http_json "/predict" "$payload")"
  [[ -z "$response" ]] && return

  ghost="$(TERM_COPILOT_RESPONSE="$response" python3 - <<'PY' 2>/dev/null
import json, os
try:
    data = json.loads(os.environ.get("TERM_COPILOT_RESPONSE", "{}"))
    print(data.get("ghost_text", ""), end="")
except Exception:
    pass
PY
)"
  [[ -z "$ghost" ]] && return

  full="$(TERM_COPILOT_RESPONSE="$response" python3 - <<'PY' 2>/dev/null
import json, os
try:
    data = json.loads(os.environ.get("TERM_COPILOT_RESPONSE", "{}"))
    print(data.get("full_command", ""), end="")
except Exception:
    pass
PY
)"
  source="$(TERM_COPILOT_RESPONSE="$response" python3 - <<'PY' 2>/dev/null
import json, os
try:
    data = json.loads(os.environ.get("TERM_COPILOT_RESPONSE", "{}"))
    print(data.get("source", ""), end="")
except Exception:
    pass
PY
)"

  TERM_COPILOT_LAST_BUFFER="$prefix"
  TERM_COPILOT_LAST_FULL="$full"
  TERM_COPILOT_LAST_SOURCE="$source"
  suggestion="${prefix}${ghost}"
}

term-copilot-accept() {
  local full="$TERM_COPILOT_LAST_FULL"
  local source="$TERM_COPILOT_LAST_SOURCE"
  if zle -l autosuggest-accept >/dev/null 2>&1; then
    zle autosuggest-accept
  elif [[ -n "$full" ]]; then
    BUFFER="$full"
    CURSOR=${#BUFFER}
  else
    zle forward-char
    return
  fi
  [[ -n "$full" ]] && _term_copilot_post_event "suggestion_accepted" "" "" "" "$full" "$source"
}
zle -N term-copilot-accept
bindkey '^F' term-copilot-accept
bindkey '^[[C' term-copilot-accept

_term_copilot_preexec() {
  TERM_COPILOT_EXEC_CMD="$1"
  TERM_COPILOT_EXEC_STARTED="${EPOCHREALTIME:-$SECONDS}"
}

_term_copilot_precmd() {
  local exit_code="$?"
  local cmd="$TERM_COPILOT_EXEC_CMD"
  [[ -z "$cmd" ]] && return
  local now="${EPOCHREALTIME:-$SECONDS}"
  local duration_ms=""
  duration_ms="$(TERM_COPILOT_START="$TERM_COPILOT_EXEC_STARTED" TERM_COPILOT_NOW="$now" python3 - <<'PY' 2>/dev/null
import os
try:
    print(int((float(os.environ.get("TERM_COPILOT_NOW", "0")) - float(os.environ.get("TERM_COPILOT_START", "0"))) * 1000), end="")
except Exception:
    print("", end="")
PY
)"
  _term_copilot_post_event "command_executed" "$cmd" "$exit_code" "$duration_ms" "" ""
  TERM_COPILOT_EXEC_CMD=""
}

autoload -Uz add-zsh-hook 2>/dev/null || true
add-zsh-hook preexec _term_copilot_preexec 2>/dev/null || true
add-zsh-hook precmd _term_copilot_precmd 2>/dev/null || true

# Put term_copilot first, but keep user's existing fallback strategies.
if [[ -z "$ZSH_AUTOSUGGEST_STRATEGY" ]]; then
  ZSH_AUTOSUGGEST_STRATEGY=(term_copilot)
else
  ZSH_AUTOSUGGEST_STRATEGY=(term_copilot ${ZSH_AUTOSUGGEST_STRATEGY[@]})
fi
