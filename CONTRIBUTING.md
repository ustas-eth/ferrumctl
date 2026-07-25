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
