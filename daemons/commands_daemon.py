import random
import re
import sys
import traceback
from pathlib import Path

# Add parent directory to path so we can import engine and utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import ask_openrouter, build_prompt_from_keyword
from mai_personality import (
    _harmful_request_response,
    _llm_flagged_response,
    _llm_flags_unsafe_request,
    _looks_like_harmful_generation_request,
    _looks_like_prompt_injection_attempt,
    _prompt_injection_response,
)
from utils.helpers import load_json, log_event, write_to_file
from utils.paths import Paths

_URL_PATTERN = re.compile(
    r'(?:https?://|www\.)\S+'                                           # http/https/www prefix
    r'|\b\w[\w\-]*\.(?:com|net|org|gg|tv|io|co|me|ly|app|dev|ai|xyz)'  # bare domain.tld
    r'(?:/\S*)?',                                                        # optional path
    re.IGNORECASE,
)

# IPv4 (octet-bounded, so "999.999.999.999" doesn't match) and full-form
# IPv6. There's no in-character reason Mai should ever emit something
# address-shaped — real or, as happened live, a hallucinated placeholder
# like a textbook example IP. Chat asking "what's your IP" should get
# deflected in-character, not answered with anything that looks like one.
_IP_PATTERN = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
    r'|\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b'
)


def _strip_urls(text: str) -> str:
    """Remove any URLs or IP addresses the model may have generated
    despite instructions — the model has no real network info in its
    prompt context, so anything address-shaped it emits is either a
    hallucinated placeholder or, worse, a real internal address; neither
    belongs in a public chat response."""
    cleaned = _URL_PATTERN.sub('', text)
    cleaned = _IP_PATTERN.sub('', cleaned)
    cleaned = ' '.join(cleaned.split())
    # A removed span at the very start often leaves a stray leading
    # connector (", and no..." after "192.168.1.1, and no...").
    cleaned = re.sub(r'^[,;:\-\s]+', '', cleaned)
    return cleaned.strip()


ROLE_ORDER = {
    "normal": 0,
    "vip": 1,
    "moderator": 2,
    "broadcaster": 3,
}

FALLBACK_RESPONSES = [
    "Mai had a command hiccup. Try that again in a moment.",
    "Command processing glitched. Please retry shortly.",
    "I missed that command timing. Run it again for me.",
]


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _normalize_level(value: str) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "mod": "moderator",
        "mods": "moderator",
        "broadcaster": "broadcaster",
        "owner": "broadcaster",
        "vip": "vip",
        "normal": "normal",
        "user": "normal",
    }
    return aliases.get(raw, "normal")


def _normalize_username_set(value) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item).strip().lower() for item in value if str(item).strip()}


def _format_message(template: str, **payload) -> str:
    return str(template or "").format_map(_SafeFormatDict(payload)).strip()


def _get_broadcaster_username(config: dict) -> str:
    monitor_cfg = config.get("monitor", {}) if isinstance(config.get("monitor", {}), dict) else {}
    channel = (
        monitor_cfg.get("twitch_channel")
        or config.get("twitch_channel")
        or monitor_cfg.get("owner_username")
        or ""
    )
    return str(channel).strip().lower()


def resolve_user_level(username: str, access_data: dict, config_data: dict) -> str:
    user = str(username or "").strip().lower()
    if not user:
        return "normal"

    broadcaster = _get_broadcaster_username(config_data)
    if broadcaster and user == broadcaster:
        return "broadcaster"

    moderator_users = _normalize_username_set(access_data.get("moderator_users", []))
    if user in moderator_users:
        return "moderator"

    vip_users = _normalize_username_set(access_data.get("vip_users", []))
    if user in vip_users:
        return "vip"

    return "normal"


def parse_command(raw_input: str) -> tuple[str, str]:
    tokens = str(raw_input or "").strip().split()
    if not tokens:
        return "", ""

    first = tokens[0].strip()
    key = first[1:] if first.startswith("!") else first
    return key.lower(), " ".join(tokens[1:]).strip()


def resolve_command(command_key: str, commands_data: dict) -> tuple[str, dict] | tuple[None, None]:
    if command_key in commands_data and isinstance(commands_data[command_key], dict):
        return command_key, commands_data[command_key]

    lookup = command_key.lower()
    for key, payload in commands_data.items():
        if not isinstance(payload, dict):
            continue
        aliases = payload.get("aliases", [])
        alias_set = {str(a).strip().lower().lstrip("!") for a in aliases if str(a).strip()}
        if lookup in alias_set:
            return key, payload

    return None, None


def has_permission(user_level: str, min_level: str) -> bool:
    return ROLE_ORDER.get(user_level, 0) >= ROLE_ORDER.get(min_level, 0)


def build_command_prompt(
    command_key: str,
    command_args: str,
    raw_input: str,
    username: str,
    user_level: str,
    min_level: str,
    command_data: dict,
    cognitive_context: str | None = None,
    mood_context: dict | None = None,
) -> str:
    # cognitive_context accepted for call-site shape compatibility with the
    # other task templates. Not wired to a live relationship_core call here
    # yet — command-abuse-triggers-Crash needs pet-peeve tracking, which is
    # spec Phase 4 (relationship mutation / observation extraction), not
    # built in this pass.
    context = {
        "command": command_key,
        "username": username,
        "user_level": user_level,
        "min_level": min_level,
        "command_description": command_data.get("description", ""),
        "command_context": command_data.get("context", ""),
        "command_usage": command_data.get("usage", f"!{command_key}"),
        "response_data": command_data.get("response_data", ""),
        "url": command_data.get("url", ""),
        "command_args": command_args,
        "raw_input": raw_input,
    }
    return build_prompt_from_keyword(
        "commands", context=context, cognitive_context=cognitive_context, mood_context=mood_context
    )


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    log_event("commands_daemon_started", {"args": sys.argv}, Paths.CALLS_LOG)

    if len(sys.argv) < 2:
        msg = "Usage: python commands_daemon.py <rawInput> [username]"
        print(msg)
        write_to_file("Mai needs a chat command like !social.", Paths.COMMAND_OUTPUT)
        sys.exit(1)

    raw_input = sys.argv[1]
    username = sys.argv[2] if len(sys.argv) >= 3 else "Anonymous"

    command_key, command_args = parse_command(raw_input)

    access_data = load_json(Paths.COMMAND_ACCESS, default={})
    commands_data = load_json(Paths.COMMANDS, default={})
    config_data = load_json(Paths.CONFIG, default={})

    invalid_input_message = access_data.get(
        "invalid_input_message",
        "@{username} - use a command like !social, !discord, or !about.",
    )
    unknown_command_message = access_data.get(
        "unknown_command_message",
        "@{username} - I do not have !{command} configured yet.",
    )
    permission_denied_message = access_data.get(
        "permission_denied_message",
        "@{username} - !{command} requires {min_level} access.",
    )

    if not command_key:
        output = _format_message(invalid_input_message, username=username)
        print(output)
        write_to_file(output, Paths.COMMAND_OUTPUT)
        log_event(
            "command_invalid_input",
            {"username": username, "raw_input": raw_input, "output": output},
            Paths.COMMAND_HISTORY,
        )
        sys.exit(0)

    resolved_key, command_cfg = resolve_command(command_key, commands_data)
    if not resolved_key or not command_cfg:
        output = _format_message(unknown_command_message, username=username, command=command_key)
        print(output)
        write_to_file(output, Paths.COMMAND_OUTPUT)
        log_event(
            "command_unknown",
            {"username": username, "raw_input": raw_input, "command": command_key, "output": output},
            Paths.COMMAND_HISTORY,
        )
        sys.exit(0)

    user_level = resolve_user_level(username, access_data, config_data)
    min_level = _normalize_level(command_cfg.get("min_level", "normal"))

    if not has_permission(user_level, min_level):
        output = _format_message(
            permission_denied_message,
            username=username,
            command=resolved_key,
            min_level=min_level,
            user_level=user_level,
        )
        print(output)
        write_to_file(output, Paths.COMMAND_OUTPUT)
        log_event(
            "command_permission_denied",
            {
                "username": username,
                "command": resolved_key,
                "raw_input": raw_input,
                "user_level": user_level,
                "required_level": min_level,
                "output": output,
            },
            Paths.COMMAND_HISTORY,
        )
        sys.exit(0)

    if _looks_like_prompt_injection_attempt(raw_input):
        response = _prompt_injection_response(username, raw_input)
        print(response)
        write_to_file(response, Paths.COMMAND_OUTPUT)
        sys.exit(0)

    if _looks_like_harmful_generation_request(raw_input):
        # Same pre-generation gate as the plain-chat path in
        # mai_personality.py: a closed list of real-world-harm categories
        # (drug synthesis, weapons/explosives, self-harm, hacking) never
        # reaches build_command_prompt/ask_openrouter at all — no prompt
        # built, no LLM call attempted.
        response = _harmful_request_response(username, raw_input)
        print(response)
        write_to_file(response, Paths.COMMAND_OUTPUT)
        sys.exit(0)

    llm_flagged_category = _llm_flags_unsafe_request(raw_input)
    if llm_flagged_category:
        response = _llm_flagged_response(username, raw_input, llm_flagged_category)
        print(response)
        write_to_file(response, Paths.COMMAND_OUTPUT)
        sys.exit(0)

    try:
        prompt = build_command_prompt(
            command_key=resolved_key,
            command_args=command_args,
            raw_input=raw_input,
            username=username,
            user_level=user_level,
            min_level=min_level,
            command_data=command_cfg,
        )
        if prompt.startswith("WARNING:"):
            raise RuntimeError(prompt)

        response = ask_openrouter(prompt, spicy=False)
        if response.startswith("WARNING:"):
            raise RuntimeError(response)

        response = _strip_urls(response)
        url = command_cfg.get("url", "").strip()
        if url:
            response = f"{response} {url}"

        print(response)
        write_to_file(response, Paths.COMMAND_OUTPUT)
        log_event(
            "command_generated",
            {
                "username": username,
                "command": resolved_key,
                "raw_input": raw_input,
                "args": command_args,
                "user_level": user_level,
                "required_level": min_level,
                "prompt": prompt,
                "response": response,
            },
            Paths.COMMAND_HISTORY,
        )
        sys.exit(0)

    except Exception as e:
        fallback = random.choice(FALLBACK_RESPONSES)
        print(fallback)
        write_to_file(fallback, Paths.COMMAND_OUTPUT)
        log_event(
            "command_generation_error",
            {
                "username": username,
                "command": resolved_key,
                "raw_input": raw_input,
                "args": command_args,
                "user_level": user_level,
                "required_level": min_level,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "error_traceback": traceback.format_exc(),
                "fallback_used": fallback,
            },
            Paths.ERROR_LOG,
        )
        sys.exit(0)
