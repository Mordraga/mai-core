"""
Mai Personality Engine
Generates context-aware responses based on message content.
The active personality is loaded from jsons/data/personalities/<id>.yaml
as configured in config.json["personality"]["active"].
"""

import random
import re
from pathlib import Path

from utils.helpers import load_json, load_yaml, resolve_existing_path
from utils.paths import Paths

# =============================
# PERSONALITY DATA LOADER
# =============================

_personality: dict | None = None


def _load_personality() -> dict:
    global _personality
    if _personality is None:
        # Use engine's active personality loader so both systems stay in sync
        try:
            from engine import _load_active_personality
            _personality = _load_active_personality()
        except Exception:
            pass
        if not _personality:
            try:
                _personality = load_yaml(Paths.PERSONALITY_YAML, default={})
            except Exception:
                _personality = load_json(Paths.PERSONALITY, default={})
    return _personality


def reload_personality() -> None:
    """Clear the personality cache so next call re-loads the active personality."""
    global _personality
    _personality = None
    _load_personality()


def _p(key: str, default=None):
    """Shorthand accessor for top-level personality keys."""
    return _load_personality().get(key, default)


def _owner_profile() -> dict[str, str]:
    config = load_json(Paths.CONFIG, default={})
    if not isinstance(config, dict):
        return {}
    profile = config.get("owner_profile", {})
    if not isinstance(profile, dict):
        return {}

    def _clean(field: str) -> str:
        return str(profile.get(field, "")).strip()

    return {
        "username": _clean("username"),
        "name": _clean("name"),
        "pronouns": _clean("pronouns"),
        "role_identity": _clean("role_identity"),
        "context_lore": _clean("context_lore"),
    }


def _owner_profile_instruction(owner_username: str) -> str:
    profile = _owner_profile()
    if not any(profile.values()):
        return ""

    username = profile.get("username") or owner_username
    name = profile.get("name") or "unknown"
    pronouns = profile.get("pronouns") or "unknown"
    role_identity = profile.get("role_identity") or "unknown"
    context_lore = profile.get("context_lore") or "none provided"

    return (
        "Owner profile details:\n"
        f"- Username: {username}\n"
        f"- Name: {name}\n"
        f"- Pronouns: {pronouns}\n"
        f"- Role/Identity: {role_identity}\n"
        f"- Context/Lore: {context_lore}\n"
        "Use this profile naturally when relevant."
    )


# Stable constant kept in Python so mai_monitor.py can import it directly.
# Falls back to the JSON value if accessed via personality().
WITCH_USERNAME: str = "mordraga0"  # <3


# =============================
# CONTEXT DETECTION
# =============================

def detect_context(message: str) -> str:
    """Detect the context/topic of a message."""
    message_lower = message.lower()
    patterns: dict[str, list[str]] = _p("context_patterns", {})
    for context, pattern_list in patterns.items():
        for pattern in pattern_list:
            if re.search(pattern, message_lower):
                return context
    return "general"


# =============================
# CONTEXTUAL PROMPT BUILDER
# =============================

# =============================
# VOICE EXAMPLES (trained from her own chat history)
# =============================

def _load_jsonl_tail(path: str, max_lines: int = 300) -> list[dict]:
    """Read a JSONL log file, returning parsed records from its last
    max_lines lines. Malformed lines are skipped."""
    import json as _json

    file_path = resolve_existing_path(path)
    if not file_path.exists():
        return []
    try:
        with file_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()[-max_lines:]
    except Exception:
        return []

    records: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = _json.loads(line)
        except Exception:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _flagged_response_texts() -> set[str]:
    """Response texts a moderator has flagged via !panic — excluded from
    the voice-example pool so bad lines never get reinforced."""
    records = _load_jsonl_tail(Paths.FLAGGED_RESPONSES, max_lines=500)
    return {str(r.get("response", "")).strip().lower() for r in records if r.get("response")}


def _recent_voice_examples(limit: int = 3) -> list[tuple[str, str]]:
    """Sample real (trigger, response) pairs from Mai's own recent
    autonomous chat history, excluding anything flagged via !panic. Grounds
    her tone in how she's actually talked in this chat, not just hand-written
    examples."""
    candidates = _load_jsonl_tail(Paths.AUTONOMOUS_HISTORY, max_lines=300)
    if not candidates:
        return []
    flagged = _flagged_response_texts()

    pool: list[tuple[float, str, str]] = []
    for entry in candidates:
        trigger = str(entry.get("trigger_message", "")).strip()
        response = str(entry.get("response", "")).strip()
        if not trigger or not response:
            continue
        if response.lower() in flagged:
            continue
        if trigger.startswith("!"):
            continue
        word_count = len(response.split())
        if word_count < 3 or word_count > 30:
            continue
        pool.append((float(entry.get("timestamp", 0.0)), trigger, response))

    if not pool:
        return []

    recent_pool = pool[-30:]
    sample_size = min(limit, len(recent_pool))
    sampled = random.sample(recent_pool, sample_size)
    sampled.sort(key=lambda item: item[0])
    return [(trigger, response) for _, trigger, response in sampled]


def _format_recent_messages(username: str, recent_messages: list[str] | None) -> str:
    if not recent_messages:
        return f"These are the last 5 messages sent by {username}:\n- [no prior messages]"
    cleaned = [str(msg).strip() for msg in recent_messages if str(msg).strip()]
    if not cleaned:
        return f"These are the last 5 messages sent by {username}:\n- [no prior messages]"
    lines = "\n".join(f"- {msg}" for msg in cleaned[-5:])
    return f"These are the last 5 messages sent by {username}:\n{lines}"


def build_contextual_prompt(
    username: str,
    message: str,
    context: str,
    recent_messages: list[str] | None = None,
    mood_context: dict | None = None,
    cognitive_context: str | None = None,
) -> tuple[str, str]:
    """Build a context-aware prompt for Mai.

    Returns a (system_prompt, user_message) tuple to prevent prompt leaking.
    The system prompt contains all instructions; the user message is just the chat line.
    """
    identity: str = _p("identity", "You are Mai, a flirty chaos familiar.")
    guidance_map: dict[str, str] = _p("context_guidance", {})
    guidance = guidance_map.get(context, guidance_map.get("general", "React naturally."))
    recent_history_block = _format_recent_messages(username, recent_messages)
    mood_name = str((mood_context or {}).get("name", "neutral")).strip() or "neutral"
    mood_guidance = str((mood_context or {}).get("guidance", "")).strip() or "No special mood guidance."
    mood_block = f"Current session mood: {mood_name}\nMood guidance: {mood_guidance}"

    voice_examples = _recent_voice_examples(limit=3)
    voice_block = ""
    if voice_examples:
        examples_text = "\n".join(
            f'- chatter said "{trigger}" -> you said "{response}"'
            for trigger, response in voice_examples
        )
        voice_block = (
            "\n\nRecent examples of how you've actually talked in this chat "
            f"(match this energy and cadence — don't repeat them verbatim):\n{examples_text}"
        )

    cognitive_block = (cognitive_context or "").strip()
    cognitive_section = f"\n\n{cognitive_block}" if cognitive_block else ""

    system = (
        f"{identity}"
        f"{cognitive_section}\n\n"
        f"Context detected: {context}\n"
        f"{recent_history_block}\n"
        f"{mood_block}\n\n"
        f"{guidance}"
        f"{voice_block}\n\n"
        f"Respond as Mai in 15-20 words. Be natural, flirty, and sassy. Reference their message directly."
    )
    user = f'[{username}]: {message}'
    return system, user


# =============================
# RESPONSE GENERATION
# =============================

_PROMPT_LEAK_PATTERNS = re.compile(
    r"^(Context detected:|These are the last|Current session mood:|Mood guidance:|"
    r"Respond as Mai|Your response:|Special instruction:|You are Mai)",
    re.IGNORECASE,
)


def _clean_llm_response(response: str) -> str:
    """Normalize model output and strip common wrappers/preambles."""
    response = str(response).strip()
    preambles = ["Here's my response:", "Mai said:", "[Mai]:", "Mai:", "Response:", "*", '"']
    for preamble in preambles:
        if response.startswith(preamble):
            response = response[len(preamble):].strip()
        if response.endswith(preamble):
            response = response[:-len(preamble)].strip()

    # Strip any lines that look like leaked prompt fragments
    lines = response.splitlines()
    clean_lines = [ln for ln in lines if not _PROMPT_LEAK_PATTERNS.match(ln.strip())]
    response = " ".join(clean_lines).strip()

    return response


def _generate_with_prompt(
    username: str,
    message: str,
    llm_backend,
    extra_guidance: str = "",
    recent_messages: list[str] | None = None,
    mood_context: dict | None = None,
    cognitive_context: str | None = None,
) -> str:
    """Shared response generation path with optional user-specific guidance."""
    context = detect_context(message)
    system_prompt, user_message = build_contextual_prompt(
        username,
        message,
        context,
        recent_messages=recent_messages,
        mood_context=mood_context,
        cognitive_context=cognitive_context,
    )

    if extra_guidance:
        system_prompt += f"\n\nSpecial instruction: {extra_guidance}"

    # Inject spice level from active mood
    spice_level = int((mood_context or {}).get("spice_level", 2))
    spice_data = load_json(Paths.SPICE, default={})
    spice_obj = spice_data.get(str(spice_level), {})
    spice_desc = str(spice_obj.get("description", "")).strip()
    spice_anchors = [str(a) for a in spice_obj.get("anchors", []) if str(a).strip()]
    if spice_desc:
        system_prompt += f"\n\nCurrent intensity: {spice_desc}"
        if spice_anchors:
            system_prompt += f"\nBehavioral anchors: {', '.join(spice_anchors)}"

    if should_add_sass(message):
        system_prompt = add_sass_modifier(system_prompt)

    response = _clean_llm_response(llm_backend(user_message, system_prompt=system_prompt, spicy=(spice_level >= 7)))

    if not response:
        return get_contextual_fallback(context)

    return response


def is_mordraga(username: str, owner_username: str = WITCH_USERNAME) -> bool:
    """Return True when the speaker is Mai's witch."""
    return username.strip().lower() == owner_username.strip().lower()


def generate_contextual_response(
    username: str,
    message: str,
    llm_backend,
    owner_username: str = WITCH_USERNAME,
    recent_messages: list[str] | None = None,
    mood_context: dict | None = None,
    cognitive_context: str | None = None,
) -> str:
    """Generate a context-aware response using Mai's personality."""
    if is_mordraga(username, owner_username=owner_username):
        return mordraga_chat(
            username,
            message,
            llm_backend,
            owner_username=owner_username,
            recent_messages=recent_messages,
            mood_context=mood_context,
            cognitive_context=cognitive_context,
        )

    return _generate_with_prompt(
        username,
        message,
        llm_backend,
        recent_messages=recent_messages,
        mood_context=mood_context,
        cognitive_context=cognitive_context,
    )


def mordraga_chat(
    username: str,
    message: str,
    llm_backend,
    owner_username: str = WITCH_USERNAME,
    recent_messages: list[str] | None = None,
    mood_context: dict | None = None,
    cognitive_context: str | None = None,
) -> str:
    """Owner-specific response path with stronger familiar-bond behavior."""
    owner_guidance: str = _p("owner_guidance", "Be extra loyal and affectionate, without being submissive.")
    owner_profile_instruction = _owner_profile_instruction(owner_username)
    combined_guidance = f"This user is {owner_username}, your witch. {owner_guidance}"
    if owner_profile_instruction:
        combined_guidance = f"{combined_guidance}\n\n{owner_profile_instruction}"
    return _generate_with_prompt(
        username=username,
        message=message,
        llm_backend=llm_backend,
        recent_messages=recent_messages,
        extra_guidance=combined_guidance,
        mood_context=mood_context,
        cognitive_context=cognitive_context,
    )


# =============================
# FALLBACK RESPONSES
# =============================

def get_contextual_fallback(context: str) -> str:
    """Get a themed fallback response based on context."""
    fallbacks: dict[str, list[str]] = _p("fallbacks", {})
    options = fallbacks.get(context) or fallbacks.get("general", ["The spirits say: noted"])
    return random.choice(options)


# =============================
# PERSONALITY TRAITS
# =============================

def should_add_sass(message: str) -> bool:
    """Determine if response should have extra sass."""
    triggers: dict = _p("sass_triggers", {})

    prefix = triggers.get("command_prefix", "!")
    if message.strip().startswith(prefix):
        return True

    min_len = triggers.get("all_caps_min_length", 5)
    if message.isupper() and len(message) > min_len:
        return True

    nature_words: list[str] = triggers.get("nature_words", ["bot", "ai", "real", "fake"])
    if any(word in message.lower() for word in nature_words):
        return True

    return False


def add_sass_modifier(prompt: str) -> str:
    """Append the sass instruction to a prompt."""
    modifier: str = _p("sass_modifier", "Be EXTRA sassy in this response.")
    return prompt + f"\n\n{modifier}"


# =============================
# EXPORTS
# =============================

__all__ = [
    "generate_contextual_response",
    "mordraga_chat",
    "is_mordraga",
    "WITCH_USERNAME",
    "detect_context",
    "get_contextual_fallback",
    "should_add_sass",
    "add_sass_modifier",
]
