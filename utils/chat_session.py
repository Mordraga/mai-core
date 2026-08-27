"""
Pure chat session logic — no tkinter, no threads.

Provides generate_chat_response() which runs the full Mai pipeline
(context detection → mood → LLM → ToS redaction) and returns a plain
ChatResult. Safe to call from a CLI, a test, or any UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from daemons.commands_daemon import (
    _format_message,
    _normalize_level,
    _strip_urls,
    build_command_prompt,
    has_permission,
    parse_command as _parse_command_input,
    resolve_command,
    resolve_user_level as _resolve_cmd_user_level,
)
from engine import ask_openrouter
from mai_personality import (
    detect_context,
    generate_contextual_response,
    get_contextual_fallback,
    is_mordraga,
    mordraga_chat,
)
from utils.helpers import apply_tos_redaction, load_json
from utils.mood_engine import resolve_effective_mood
from utils.paths import Paths


@dataclass
class ChatResult:
    response: str
    flagged_terms: list[str] = field(default_factory=list)
    context: str = "general"
    mood: str = "neutral"
    is_command: bool = False
    llm_error: str | None = None


def _run_command(
    username: str,
    message: str,
    owner_username: str,
    platform: str,
    redaction_data: dict,
) -> ChatResult | None:
    """Try to handle message as a command. Returns ChatResult or None if not a command."""
    cfg = load_json(Paths.CONFIG, default={})
    prefix = str(cfg.get("monitor", {}).get("command_prefix", "!")).strip()
    prefix = prefix[0] if prefix else "!"

    tokens = message.strip().split()
    if not tokens or not tokens[0].startswith(prefix) or len(tokens[0]) <= len(prefix):
        return None

    commands_data = load_json(Paths.COMMANDS, default={})
    access_data = load_json(Paths.COMMAND_ACCESS, default={})

    command_key, command_args = _parse_command_input(message)
    if not command_key:
        return None

    resolved_key, command_cfg = resolve_command(command_key, commands_data)

    if not resolved_key or not command_cfg:
        # Unknown command — in-character reaction
        mood_context = resolve_effective_mood("monitor", require_active_session=False)
        mood_name = str(mood_context.get("name", "neutral"))
        prompt = (
            f"A user named {username} just typed '{prefix}{command_key}' in chat. "
            f"That is not a registered command. React briefly in character as Mai — dry, a little cryptic. "
            f"Current mood: {mood_name}. One or two sentences max."
        )
        response = ask_openrouter(prompt, spicy=False)
        if not response or response.startswith("WARNING:"):
            response = "That command doesn't exist in my archives."
        flagged: list[str] = []
        if platform == "twitch":
            response, flagged = apply_tos_redaction(response, redaction_data)
        return ChatResult(response=response, flagged_terms=flagged, context="command", mood=mood_name, is_command=True)

    user_level = _resolve_cmd_user_level(username, access_data, cfg)
    min_level = _normalize_level(command_cfg.get("min_level", "normal"))

    if not has_permission(user_level, min_level):
        denied_tmpl = access_data.get(
            "permission_denied_message",
            "@{username} - !{command} requires {min_level} access.",
        )
        output = _format_message(
            denied_tmpl,
            username=username,
            command=resolved_key,
            min_level=min_level,
            user_level=user_level,
        )
        return ChatResult(response=output, context="command", mood="neutral", is_command=True)

    prompt = build_command_prompt(
        command_key=resolved_key,
        command_args=command_args,
        raw_input=message,
        username=username,
        user_level=user_level,
        min_level=min_level,
        command_data=command_cfg,
    )

    mood_context = resolve_effective_mood("monitor", require_active_session=False)
    mood_name = str(mood_context.get("name", "neutral"))

    try:
        response = ask_openrouter(prompt, spicy=False)
        if response.startswith("WARNING:"):
            raise RuntimeError(response)
        response = _strip_urls(response)
        url = command_cfg.get("url", "").strip()
        if url:
            response = f"{response} {url}"
    except Exception:
        response = f"Command !{resolved_key} ran into an issue. Try again."

    flagged = []
    if platform == "twitch":
        response, flagged = apply_tos_redaction(response, redaction_data)

    return ChatResult(response=response, flagged_terms=flagged, context="command", mood=mood_name, is_command=True)


def generate_chat_response(
    username: str,
    message: str,
    owner_username: str,
    platform: str,
    redaction_data: dict,
    recent_messages: list[str] | None = None,
    spice_override: int | None = None,
) -> ChatResult:
    """
    Run the full Mai response pipeline and return a ChatResult.

    Mirrors MaiMonitor.generate_response + autonomous_response but as a
    pure function with no IRC side-effects. Caller provides all config
    values so this function never touches the filesystem itself.

    Args:
        username:       Display name of the person chatting.
        message:        Their message text.
        owner_username: Channel owner username (routes to mordraga_chat).
        platform:       "twitch" or "fansly" — controls ToS redaction.
        redaction_data: The "redaction" dict from redaction.json.
    """
    cmd_result = _run_command(username, message, owner_username, platform, redaction_data)
    if cmd_result is not None:
        return cmd_result

    context = detect_context(message)
    mood_context = resolve_effective_mood("monitor", require_active_session=False)
    mood_name = str(mood_context.get("name", "neutral"))
    if spice_override is not None:
        mood_context = dict(mood_context)
        mood_context["spice_level"] = max(1, min(11, int(spice_override)))

    try:
        if is_mordraga(username, owner_username=owner_username):
            response = mordraga_chat(
                username=username,
                message=message,
                llm_backend=ask_openrouter,
                owner_username=owner_username,
                mood_context=mood_context,
                recent_messages=recent_messages,
            )
        else:
            response = generate_contextual_response(
                username=username,
                message=message,
                llm_backend=ask_openrouter,
                owner_username=owner_username,
                mood_context=mood_context,
                recent_messages=recent_messages,
            )

        if response.startswith("WARNING:"):
            raise RuntimeError(response)

    except Exception as _exc:
        return ChatResult(
            response=get_contextual_fallback(context),
            context=context,
            mood=mood_name,
            llm_error=str(_exc),
        )

    flagged: list[str] = []
    if platform == "twitch":
        response, flagged = apply_tos_redaction(response, redaction_data)

    return ChatResult(
        response=response,
        flagged_terms=flagged,
        context=context,
        mood=mood_name,
    )
