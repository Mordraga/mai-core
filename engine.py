import re
import requests
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml as _yaml

from utils.helpers import load_json, load_config, load_keys, log_event, resolve_existing_path
from utils.paths import Paths

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_RP_PATTERN = re.compile(r"\*[^*\n]+\*")


def strip_rp_formatting(text: str) -> str:
    """Strip asterisk-style roleplay actions (*smiles*, *laughs*, etc.) from model output."""
    cleaned = _RP_PATTERN.sub("", text)
    return " ".join(cleaned.split()).strip()


# =============================
# Personality helpers
# =============================

def _load_active_personality() -> dict:
    """Load the active personality YAML. Falls back to witch_familiar on any error."""
    try:
        config = load_config()
        active_id = config.get("personality", {}).get("active", "witch_familiar")
        personalities_dir = resolve_existing_path(Paths.PERSONALITIES_DIR)
        yaml_path = personalities_dir / f"{active_id}.yaml"
        if not yaml_path.exists():
            yaml_path = personalities_dir / "witch_familiar.yaml"
        with open(yaml_path, encoding="utf-8") as fh:
            return _yaml.safe_load(fh) or {}
    except Exception:
        return {}


def get_personality_spice_params(requested_spice: int) -> tuple[int, bool]:
    """Return (clamped_spice, use_spicy_temperature) for the active personality."""
    personality = _load_active_personality()
    if not personality.get("has_spice", True):
        return 1, False
    max_spice = int(personality.get("max_spice", 10))
    clamped = min(int(requested_spice), max_spice)
    return clamped, clamped >= 7


# =============================
# Prompt Templates
# =============================

class _TemplateSafeDict(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _normalize_context_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _normalize_context(context: Mapping[str, Any] | None) -> dict[str, str]:
    if not context:
        return {}
    return {
        str(key): _normalize_context_value(value)
        for key, value in context.items()
    }


def _resolve_template_key(keyword: str, registry: Mapping[str, Any]) -> str:
    route = registry.get(keyword, {})
    if isinstance(route, Mapping):
        return str(route.get("prompt_template") or route.get("template") or keyword)
    return keyword


def get_prompt_template(
    keyword: str,
    registry: Mapping[str, Any] | None = None,
    templates: Mapping[str, Any] | None = None,
) -> str | None:
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return None

    registry_data = registry if registry is not None else load_json(Paths.REGISTRY, default={})
    template_data = templates if templates is not None else load_json(Paths.PROMPT_TEMPLATES, default={})

    template_key = _resolve_template_key(keyword, registry_data)
    template_entry = template_data.get(template_key) or template_data.get(keyword)

    if isinstance(template_entry, Mapping):
        template_text = template_entry.get("prompt") or template_entry.get("template")
        if template_text:
            return str(template_text)
        return None

    if isinstance(template_entry, str):
        return template_entry

    return None


def build_prompt_from_keyword(
    keyword: str,
    context: Mapping[str, Any] | None = None,
    registry: Mapping[str, Any] | None = None,
    templates: Mapping[str, Any] | None = None,
    cognitive_context: str | None = None,
    mood_context: Mapping[str, Any] | None = None,
) -> str:
    template_data = templates if templates is not None else load_json(Paths.PROMPT_TEMPLATES, default={})
    registry_data = registry if registry is not None else load_json(Paths.REGISTRY, default={})

    # Load active personality for identity injection
    personality = _load_active_personality()
    config = load_config()
    owner_username = config.get("monitor", {}).get("owner_username", "")

    normalized_context = _normalize_context(context)
    normalized_context.setdefault("owner_username", owner_username)
    normalized_context.setdefault("name", personality.get("name", "Mai"))
    normalized_context.setdefault("voice_hint", personality.get("voice_hint", "dry, cryptic, warm"))
    safe = _TemplateSafeDict(normalized_context)

    template_key = _resolve_template_key(keyword, registry_data)
    entry = template_data.get(template_key) or template_data.get(keyword)
    base = template_data.get("base", "")
    task = template_data.get("tasks", {}).get(keyword, "")

    # Apply personality reframe for no-spice personalities (flirt, tarot)
    if not personality.get("has_spice", True):
        reframe_key = f"{keyword}_reframe"
        reframe = personality.get(reframe_key)
        if reframe and task:
            task = reframe

    # New-style: base + tasks map both exist for this keyword
    if base and task and isinstance(entry, Mapping):
        safe["task"] = task
        body = str(entry.get("template") or entry.get("prompt") or "")
        rendered = (base.format_map(safe) + "\n\n" + body.format_map(safe)).strip()
    else:
        # Old-style fallback: plain string template or no base/task defined
        template = get_prompt_template(keyword, registry=registry_data, templates=template_data)
        if not template:
            return (
                f"WARNING: Missing prompt template for keyword '{keyword}' "
                f"in {Paths.PROMPT_TEMPLATES}"
            )
        rendered = template.format_map(safe).strip()

    # Prepend personality identity block so the LLM knows who it is, with
    # session mood and the relationship/needs/Parts cognitive context (when
    # supplied) placed between identity and the task body per the spec's
    # PERSONALITY + COGNITIVE + TASK ordering.
    #
    # mood_context gets its own guaranteed block here rather than relying
    # on the template text referencing {mood_name}/{mood_guidance} from the
    # context dict — a template that omits those placeholders would
    # otherwise silently drop mood from the prompt entirely.
    identity = personality.get("identity", "").strip()

    mood_name = str((mood_context or {}).get("name", "")).strip()
    mood_guidance = str((mood_context or {}).get("guidance", "")).strip()
    mood_block = ""
    if mood_context and (mood_name or mood_guidance):
        mood_block = (
            f"Current session mood: {mood_name or 'neutral'}\n"
            f"Mood guidance: {mood_guidance or 'No special mood guidance.'}"
        )

    cognitive_block = (cognitive_context or "").strip()

    blocks = [b for b in (identity, mood_block, cognitive_block) if b]
    if blocks:
        return "\n\n---\n\n".join(blocks + [rendered])
    return rendered


# =============================
# OpenRouter Backend
# =============================

def ask_openrouter(
    prompt: str,
    spicy: bool = False,
    system_prompt: str | None = None,
    max_tokens: int | None = None,
) -> str:
    config = load_config()
    keys = load_keys()

    mai_config = config.get("Mai-config", config)

    api_key = keys.get("openrouter_api_key")
    if not api_key:
        return f"WARNING: Missing OpenRouter API key in {Paths.KEYS}"

    model = mai_config.get("model", "mistralai/mistral-7b-instruct")
    if max_tokens is None:
        max_tokens = mai_config.get("max_tokens", 60)
    temp_key = "temperature_spicy" if spicy else "temperature_normal"
    temperature = mai_config.get(temp_key, mai_config.get("temperature_normal", 0.85))
    timeout = mai_config.get("timeout", 30)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "FlirtDaemon",
    }

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
        if not r.ok:
            detail = r.text[:500]
            try:
                data = r.json()
                err = data.get("error", {}) if isinstance(data, dict) else {}
                msg = str(err.get("message") or "").strip()
                metadata = err.get("metadata", {}) if isinstance(err, dict) else {}
                raw_payload = metadata.get("raw") if isinstance(metadata, dict) else None

                provider_msg = ""
                if isinstance(raw_payload, str) and raw_payload.strip():
                    try:
                        raw_data = json.loads(raw_payload)
                        provider_msg = str(raw_data.get("error", {}).get("message") or "").strip()
                    except Exception:
                        provider_msg = ""

                bits = [part for part in [msg, provider_msg] if part]
                if bits:
                    detail = " | ".join(bits)
            except ValueError:
                pass

            raise requests.HTTPError(f"{r.status_code} {r.reason}: {detail}", response=r)

        data = r.json()
        try:
            content = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, ValueError) as e:
            log_event("openrouter_error", {"error": f"malformed response: {e}", "raw": str(data)[:300]}, Paths.ERROR_LOG)
            return "WARNING: OpenRouter returned a malformed response"
        return strip_rp_formatting(content)

    except requests.RequestException as e:
        log_event("openrouter_error", {"error": str(e)}, Paths.ERROR_LOG)
        return f"WARNING: OpenRouter error: {e}"


# =============================
# Unified Entry Point
# =============================

def ask_model(prompt: str, backend: str = "openrouter", spicy: bool = False) -> str:
    if backend == "openrouter":
        return ask_openrouter(prompt, spicy=spicy)
    return "WARNING: No valid backend selected."
