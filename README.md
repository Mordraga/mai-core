# mai-core

Mai's backend: the OpenRouter/LLM engine, prompt templating, personality loading, mood
session state, and command resolution logic. Platform-agnostic — no Twitch/Discord/UI
code lives here.

Consumed by [MaiDaemon](https://github.com/Mordraga/MaiDaemon) (the PySide6 control
panel + Twitch monitor) as an installed dependency, not vendored code.

## Install

Local development (editable, picks up changes immediately):

```bash
pip install -e ../mai-core
```

From another machine / CI:

```bash
pip install git+https://github.com/Mordraga/mai-core.git
```

## Data / config

This package ships code only — no `jsons/` data or config files. It reads/writes
relative paths defined in `utils/paths.py` (`Paths.CONFIG`, `Paths.MOODS`, etc.)
resolved relative to the *consuming app's* working directory. The consuming app
must either run with its own data root as the current working directory, or set
the `MAI_APP_ROOT` environment variable explicitly.

## Tests

```bash
python -m unittest discover tests
```
