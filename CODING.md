# Coding guidelines

Apply these when writing, changing, reviewing, or simplifying code.
Product and hardware rules are in [AGENTS.md](AGENTS.md).

## Checklist

- Does this need to exist? If not, skip it.
- Does the standard library do it? Use it.
- Does GTK, GLib, systemd, or the kernel already provide it? Use it.
- Does an installed dependency do it? Use it.
- Does it fit on one line? Keep it on one line.
- Only then write the minimum that works.

## Anti-patterns to avoid

- Implicit coupling: pass dependencies explicitly.
- Layer-first folders: group by feature, unless the project already follows a set structure. This project's `control_center/` (unprivileged app) and `hardware/` (root daemon) split is a privilege boundary; keep it.
- Representable illegal states: model states as separate types or enums.
- Pass-through wrappers: call the underlying thing directly.
- Errors and validation away from the boundary: parse input once at entry and trust it inside. Here the daemon validates every socket request on arrival, independently of the GUI.

## Python

- Code passes `ruff check .` with the repository `ruff.toml`; its `ANN` rules require type hints on every function.
- Use precise types, not `typing.Any`, casts, or `# type: ignore`; ruff checks that hints exist, not that they are correct.
- Match the surrounding file's style; most modules use compact spacing.
- Prefer clear names and reuse of existing helpers over new ones.
- No hardware access at import time.
- Never call GTK from a worker thread.
- Stop every timer when its window closes.

## Comments and docstrings

- Docstrings explain what the function or class does instead of repeating its name.
- Describe current behavior only; history belongs in git.
- Finish a sentence on one line when it fits, and start each new sentence on a new line.
- In lists, keep all sentences of one item on the item's line.
