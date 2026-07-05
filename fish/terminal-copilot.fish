# terminal-copilot fish integration
# Fish MVP: Ctrl+F requests one suggestion and inserts it into the commandline.

status is-interactive; or return 0

set -q TERM_COPILOT_HOST; or set -gx TERM_COPILOT_HOST 127.0.0.1
set -q TERM_COPILOT_PORT; or set -gx TERM_COPILOT_PORT 8765
set -q TERM_COPILOT_URL; or set -gx TERM_COPILOT_URL http://$TERM_COPILOT_HOST:$TERM_COPILOT_PORT
set -q TERM_COPILOT_TIMEOUT; or set -gx TERM_COPILOT_TIMEOUT 0.20

function __term_copilot_fish_is_root_mode
    set -q TERM_COPILOT_ROOT_MODE; and test "$TERM_COPILOT_ROOT_MODE" = 1; and return 0
    test (id -u 2>/dev/null) = 0; and return 0
    return 1
end

if not set -q TERM_COPILOT_SOCKET
    if not __term_copilot_fish_is_root_mode
        set -l home "$HOME"
        if set -q TERM_COPILOT_HOME
            set home "$TERM_COPILOT_HOME"
        end
        set -gx TERM_COPILOT_SOCKET "$home/.cache/term-copilot/daemon.sock"
    end
end

function __term_copilot_fish_json_get_string
    set -l response "$argv[1]"
    set -l key "$argv[2]"
    env TERM_COPILOT_RESPONSE="$response" TERM_COPILOT_KEY="$key" python3 -c '
import json
import os
try:
    value = json.loads(os.environ.get("TERM_COPILOT_RESPONSE", "{}")).get(os.environ.get("TERM_COPILOT_KEY", ""), "")
    print(value if isinstance(value, str) else "", end="")
except Exception:
    pass
' 2>/dev/null
end

function __term_copilot_fish_predict
    set -l buffer (commandline)
    set -l cursor (commandline -C)
    set -l effective_uid (id -u 2>/dev/null; or echo "")
    set -l original_user ""
    set -q SUDO_USER; and set original_user "$SUDO_USER"
    set -l root_mode false
    __term_copilot_fish_is_root_mode; and set root_mode true

    if test "$root_mode" = true; and not set -q TERM_COPILOT_SOCKET
        return 1
    end

    env TERM_COPILOT_BUFFER="$buffer" \
    TERM_COPILOT_CURSOR="$cursor" \
    TERM_COPILOT_CWD="$PWD" \
    TERM_COPILOT_EFFECTIVE_UID="$effective_uid" \
    TERM_COPILOT_ROOT_MODE_VALUE="$root_mode" \
    TERM_COPILOT_ORIGINAL_USER="$original_user" \
    python3 -c '
import json
import os
import socket
import urllib.request

def int_or_none(value):
    try:
        return int(value)
    except Exception:
        return None

payload = {
    "protocol_version": 1,
    "buffer": os.environ.get("TERM_COPILOT_BUFFER", ""),
    "cursor": int_or_none(os.environ.get("TERM_COPILOT_CURSOR")),
    "cwd": os.environ.get("TERM_COPILOT_CWD"),
    "shell": "fish",
    "user": os.environ.get("USER"),
    "effective_uid": int_or_none(os.environ.get("TERM_COPILOT_EFFECTIVE_UID")),
    "original_user": os.environ.get("TERM_COPILOT_ORIGINAL_USER") or os.environ.get("TERM_COPILOT_USER"),
    "term_copilot_home": os.environ.get("TERM_COPILOT_HOME"),
    "root_mode": os.environ.get("TERM_COPILOT_ROOT_MODE_VALUE") == "true",
}
raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
timeout = float(os.environ.get("TERM_COPILOT_TIMEOUT", "0.20"))
socket_path = os.environ.get("TERM_COPILOT_SOCKET") or ""

if socket_path and os.path.exists(socket_path) and hasattr(socket, "AF_UNIX"):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(socket_path)
            client.sendall(raw)
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

if payload["root_mode"]:
    raise SystemExit

try:
    url = os.environ.get("TERM_COPILOT_URL", "http://127.0.0.1:8765") + "/predict"
    req = urllib.request.Request(url, data=raw[:-1], headers={"Content-Type": "application/json"})
    print(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"), end="")
except Exception:
    pass
' 2>/dev/null
end

function __term_copilot_fish_event_json
    set -l event "$argv[1]"
    set -l command "$argv[2]"
    set -l exit_code "$argv[3]"
    set -l suggestion "$argv[4]"
    set -l source "$argv[5]"
    set -l effective_uid (id -u 2>/dev/null; or echo "")
    set -l root_mode false
    __term_copilot_fish_is_root_mode; and set root_mode true

    env TERM_COPILOT_EVENT="$event" \
    TERM_COPILOT_COMMAND="$command" \
    TERM_COPILOT_EXIT_CODE="$exit_code" \
    TERM_COPILOT_SUGGESTION="$suggestion" \
    TERM_COPILOT_SOURCE="$source" \
    TERM_COPILOT_CWD="$PWD" \
    TERM_COPILOT_EFFECTIVE_UID="$effective_uid" \
    TERM_COPILOT_ROOT_MODE_VALUE="$root_mode" \
    python3 -c '
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
    "suggestion": os.environ.get("TERM_COPILOT_SUGGESTION") or None,
    "source": os.environ.get("TERM_COPILOT_SOURCE") or None,
    "cwd": os.environ.get("TERM_COPILOT_CWD"),
    "shell": "fish",
    "exit_code": int_or_none(os.environ.get("TERM_COPILOT_EXIT_CODE")),
    "effective_uid": int_or_none(os.environ.get("TERM_COPILOT_EFFECTIVE_UID")),
    "root_mode": os.environ.get("TERM_COPILOT_ROOT_MODE_VALUE") == "true",
    "original_user": os.environ.get("SUDO_USER") or os.environ.get("TERM_COPILOT_USER"),
    "term_copilot_home": os.environ.get("TERM_COPILOT_HOME"),
}
print(json.dumps(payload, ensure_ascii=False), end="")
' 2>/dev/null
end

function __term_copilot_fish_post_event
    if __term_copilot_fish_is_root_mode; and not set -q TERM_COPILOT_SOCKET
        return 1
    end
    set -l payload (__term_copilot_fish_event_json $argv)
    test -n "$payload"; or return 1
    env TERM_COPILOT_PAYLOAD="$payload" python3 -c '
import os
import urllib.request
try:
    url = os.environ.get("TERM_COPILOT_URL", "http://127.0.0.1:8765") + "/events"
    req = urllib.request.Request(url, data=os.environ.get("TERM_COPILOT_PAYLOAD", "{}").encode("utf-8"), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=0.25).read()
except Exception:
    pass
' >/dev/null 2>&1 &
end

function term_copilot_fish_accept
    set -l response (__term_copilot_fish_predict)
    test -n "$response"; or return
    set -l full (__term_copilot_fish_json_get_string "$response" full_command)
    test -n "$full"; or return
    commandline --replace "$full"
    commandline -C (string length -- "$full")
    set -l source (__term_copilot_fish_json_get_string "$response" source)
    __term_copilot_fish_post_event suggestion_accepted "" "" "$full" "$source"
end

function __term_copilot_fish_postexec --on-event fish_postexec
    set -l status_code $status
    set -l command "$argv"
    test -n "$command"; or return
    __term_copilot_fish_post_event command_executed "$command" "$status_code" "" ""
end

bind \cf term_copilot_fish_accept
