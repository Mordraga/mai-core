import json
import os
import random
import re
import sys
import yaml
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time
from typing import Any, Iterable, Mapping


# ============================
# Filesystem + data helpers
# ============================

def _candidate_app_roots(include_meipass: bool = True) -> list[Path]:
    """Return candidate roots in priority order.

    When frozen (PyInstaller onedir):
      - exe_dir  : user-writable data; highest priority for both reads and writes
      - _MEIPASS : bundled read-only defaults; fallback for reads only
    When running from source:
      - MAI_APP_ROOT env var, if the consuming app sets one explicitly
      - current working directory

    This package ships as an installed dependency of the app that actually owns
    the data files (jsons/, etc.), so `Path(__file__)`-relative resolution would
    point inside this package's own install location, not the consumer's data
    directory. The consumer is expected to run with its own root as the CWD
    (as MaiDaemon's entry points already do) or set MAI_APP_ROOT explicitly.
    """
    roots: list[Path] = []

    if getattr(sys, "frozen", False):
        # exe_dir first — this is the source of truth for all runtime data
        exe_dir = Path(sys.executable).resolve().parent
        roots.append(exe_dir)
        # _MEIPASS/_internal second — bundled defaults, read-only fallback
        if include_meipass:
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                roots.append(Path(meipass))

    env_root = os.environ.get("MAI_APP_ROOT")
    if env_root:
        roots.append(Path(env_root).resolve())

    roots.append(Path.cwd())

    unique_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        unique_roots.append(root)
    return unique_roots


def resolve_existing_path(file_path: str | Path) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        if path.exists():
            return path
        # Absolute path doesn't exist yet (e.g. exe_dir/jsons/... before first write).
        # Strip the known-root prefix and search all roots including _internal defaults.
        for root in _candidate_app_roots(include_meipass=True):
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            for search_root in _candidate_app_roots(include_meipass=True):
                candidate = search_root / rel
                if candidate.exists():
                    return candidate
        return path

    if path.exists():
        return path

    for root in _candidate_app_roots(include_meipass=True):
        candidate = root / path
        if candidate.exists():
            return candidate

    return path


def resolve_write_path(file_path: str | Path) -> Path:
    path = Path(file_path)
    if path.is_absolute():
        return path

    # Only search writable roots (never _MEIPASS/bundled files)
    write_roots = _candidate_app_roots(include_meipass=False)

    # Prefer an existing file in a writable location
    for root in write_roots:
        candidate = root / path
        if candidate.exists():
            return candidate

    # No existing writable copy — pick first root where parent exists or will be created
    for root in write_roots:
        candidate = root / path
        if candidate.parent.exists():
            return candidate

    # Last resort: first write root (ensure_parent_dir will create the directory)
    if write_roots:
        return write_roots[0] / path
    return path


def ensure_parent_dir(file_path: str | Path) -> Path:
    path = resolve_write_path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_json(file_path: str | Path, default: Any = None) -> Any:
    path = resolve_existing_path(file_path)
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"JSON file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        if default is not None:
            return default
        raise ValueError(f"JSON file is empty: {path}")
    return json.loads(content)


def load_yaml(file_path: str | Path, default: Any = None) -> Any:
    path = resolve_existing_path(file_path)
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"YAML file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        if default is not None:
            return default
        raise ValueError(f"YAML file is empty: {path}")
    return yaml.safe_load(content)


def atomic_write_yaml(file_path: str | Path, payload: Any) -> None:
    serialized = yaml.dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    atomic_write_text(file_path, serialized)


def atomic_write_text(file_path: str | Path, text: str, encoding: str = "utf-8") -> None:
    path = ensure_parent_dir(file_path)
    with NamedTemporaryFile("w", encoding=encoding, dir=path.parent, delete=False) as tmp_file:
        tmp_file.write(text)
        tmp_name = tmp_file.name
    os.replace(tmp_name, path)


def atomic_write_json(
    file_path: str | Path,
    payload: Any,
    ensure_ascii: bool = False,
    indent: int = 2,
) -> None:
    serialized = json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent)
    atomic_write_text(file_path, serialized + "\n")


def append_jsonl(file_path: str | Path, record: Mapping[str, Any], ensure_ascii: bool = False) -> None:
    path = ensure_parent_dir(file_path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=ensure_ascii) + "\n")


def append_jsonl_many(
    file_path: str | Path,
    records: Iterable[Mapping[str, Any]],
    ensure_ascii: bool = False,
) -> None:
    path = ensure_parent_dir(file_path)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=ensure_ascii) + "\n")


def write_to_file(content: str, file_path: str | Path, append_newline: bool = True) -> None:
    text = content + ("\n" if append_newline else "")
    atomic_write_text(file_path, text)


def sanitize_path_component(value: str, replacement: str = "_") -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", replacement, str(value))


# ============================
# Time + secret helpers
# ============================

def utc_now_unix() -> int:
    return int(time())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_secret(
    keys: Mapping[str, Any] | None,
    env_var: str,
    key_name: str,
    default: str | None = None,
) -> str | None:
    env_value = os.getenv(env_var)
    if env_value:
        return env_value
    if keys and key_name in keys and keys[key_name]:
        return str(keys[key_name])
    return default


# ============================
# Loaders
# ============================

def load_config() -> dict:
    from utils.paths import Paths
    return load_json(Paths.CONFIG)


def load_keys() -> dict:
    from utils.paths import Paths
    return load_json(Paths.KEYS)


# ============================
# Redaction
# ============================

def apply_redaction(text: str, level: int, redaction_data: dict, style: str | None = None) -> str:
    threshold = redaction_data.get("threshold") or 7
    max_replacements = redaction_data.get("max_replacements", 1)
    filler_words = set(redaction_data.get("ignored_words", []))

    if level < threshold:
        return text

    styles = redaction_data.get("styles", {})
    if not styles:
        return text

    if style is None:
        style = random.choice(list(styles.keys()))

    style_pool = styles.get(style, ["[REDACTED]"])
    if not style_pool:
        return text

    # Target longer words only (avoid breaking short syntax words)
    candidates = [
        word
        for word in re.findall(r"\b[A-Za-z]{5,}\b", text)
        if word.lower() not in filler_words
        and not word.lower().endswith("ly")  # skip adverbs
        and not word.lower().endswith("ing")  # skip gerunds
    ]
    if not candidates:
        return text

    targets = random.sample(candidates, min(max_replacements, len(candidates)))

    for word in targets:
        replacement_token = random.choice(style_pool)
        text = re.sub(rf"\b{re.escape(word)}\b", replacement_token, text, count=1)

    return text


def apply_tos_redaction(text: str, redaction_data: dict) -> tuple[str, list[str]]:
    """
    Replace Twitch ToS-violating terms in *text* with ***.

    Returns (cleaned_text, list_of_matched_terms).
    Only applies when called — callers decide based on platform mode.
    """
    terms: list[str] = redaction_data.get("twitch_tos_terms", [])
    if not terms:
        return text, []

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b",
        re.IGNORECASE,
    )

    matched: list[str] = []

    def _replace(m: re.Match) -> str:
        matched.append(m.group(0))
        return "***"

    cleaned = pattern.sub(_replace, text)
    return cleaned, matched


# ============================
# Logging
# ============================

def write_to_log(entry: Mapping[str, Any], file_path: str | Path) -> None:
    append_jsonl(file_path, entry)


def log_event(event_type: str, payload: Mapping[str, Any], file_path: str | Path) -> None:
    entry = {
        **payload,
        "event": event_type,
        "timestamp": utc_now_unix(),
    }
    write_to_log(entry, file_path)


# ============================
# Runtime directory bootstrap
# ============================

_RUNTIME_DIRS = [
    "jsons/logs/history/users",
    "jsons/logs/errors",
    "jsons/logs/events",
    "jsons/logs/prompts",
    "jsons/calls",
    "jsons/output",
]


def bootstrap_runtime_dirs() -> None:
    """Create runtime data directories if they don't exist.

    Resolves paths the same way write paths do — beside the exe when
    packaged, or in the source tree root when running from Python.
    """
    write_roots = _candidate_app_roots(include_meipass=False)
    base = write_roots[0] if write_roots else Path(".")
    for rel in _RUNTIME_DIRS:
        (base / rel).mkdir(parents=True, exist_ok=True)


# ============================
# Parse Streamer.bot
# ============================

def parse_all_params(command_str: str) -> dict:
    """Parse theme, tone, spice, spread, and question from any rawInput string.

    Agnostically collects whatever it can find. Each value is None when not
    found — callers apply their own defaults. Unconsumed tokens are joined into
    ``question`` (useful for tarot readings).
    """
    from utils.paths import Paths  # local import to avoid circular dependency

    themes = load_json(Paths.THEMES, default={})
    tones = load_json(Paths.TONES, default={})
    spice_levels = load_json(Paths.SPICE, default={})
    spreads = load_json(Paths.TAROT_SPREADS, default={})

    result: dict = {
        "theme": None,
        "tone": None,
        "spice": None,
        "spread": None,
        "question": "",
    }

    question_tokens: list[str] = []

    for token in command_str.split():
        cleaned = token.strip().lower().rstrip(".,!?\"'")

        if cleaned in themes and result["theme"] is None:
            result["theme"] = cleaned
        elif cleaned in tones and result["tone"] is None:
            result["tone"] = cleaned
        elif cleaned.isdigit() and cleaned in spice_levels and result["spice"] is None:
            result["spice"] = int(cleaned)
        elif cleaned in spreads and result["spread"] is None:
            result["spread"] = cleaned
        else:
            question_tokens.append(token)

    result["question"] = " ".join(question_tokens).strip()
    return result
