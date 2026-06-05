# Repository Rules

- Keep tools small, Unix-style, and scriptable. Prefer clear commands, stable
  text/JSON output, stdin/stdout, exit codes, and composition with normal shell
  tools.
- Keep CLIs neutral and skills opinionated. A command should expose primitives;
  a Codex skill may describe a workflow on top of those primitives.
- Do not add wrapper commands, daemons, or shared abstractions until repeated
  real use proves they simplify the system.
- Keep docs short, literal, and user-facing. Remove stale standalone-repo
  references; `ferrumctl` is the canonical repo.
- Edit canonical docs under `docs/` or `packages/*/docs/`; update generated
  skill references with `python3 scripts/sync-skill-references.py`.
- Preserve explicit binary names such as `codex-goalctl`; `ferrumctl` is the suite
  and documentation home, not a command name.
