# Contributing

Enable the repository hooks once per checkout:

```sh
git config core.hooksPath .githooks
```

Commit headers use `type(scope): description`:

```text
feat(threadctl): make worker progress inspectable
fix(repo): prevent release version downgrades
docs(wakectl): distinguish durable wakes from active polling
```

Use the affected command as the scope. Use `repo` for cross-package work and
`release` for release-only changes. The hook prints the complete type and scope
lists when a message is rejected. Git-generated merge, revert, and autosquash
messages remain valid.

The description should preserve why the change matters: the problem it solves,
the behavior it protects, or the outcome it enables. Do not narrate filenames
or mechanics already visible in the diff. When the reason or tradeoff does not
fit naturally in the header, explain it in the commit body.

Run `./scripts/check.sh` before committing.

Thread configuration also has an opt-in integration test against a real Codex
binary. It uses a temporary Codex home, synthetic skills, and a local mock model;
it does not use account credentials or contact the running app server:

```sh
CODEX_THREADCTL_TEST_BINARY=/absolute/path/to/codex \
  PYTHONPATH=packages/codex-threadctl/src \
  python3 -m unittest discover -s packages/codex-threadctl/tests -p test_config_native.py -v
```

## Publishing Changes

Use a branch and pull request for changes to command behavior, persisted state,
compatibility, package versions, installed skills, or more than one package.
Run the repository checks before review. Squash-merge by default, retain
separate commits only when each remains independently useful, and delete the
branch after merging.

Direct commits to `main` are reserved for small maintenance changes that cannot
affect installed behavior, such as typo fixes, broken links, and repository
housekeeping. When the boundary is unclear, use a pull request.

Publishing means merging the approved change to `main`, then updating the local
commands and plugins when needed. Add tags or GitHub releases only when a
distribution or historical package boundary requires them.
