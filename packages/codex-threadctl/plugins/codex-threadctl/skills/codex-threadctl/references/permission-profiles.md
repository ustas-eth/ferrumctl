<!-- Generated from packages/codex-threadctl/docs/permission-profiles.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Permission Profiles

Threadctl selects Codex permissions when creating an independent root. Codex
defines and enforces the policy.

Use the official [permissions documentation](https://developers.openai.com/codex/permissions)
for profile syntax, built-ins, inheritance, path rules, networking, and
configuration precedence. Use the [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md)
for instruction discovery. This page covers the threadctl boundary and observed
compatibility issues.

## Selecting A Profile

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project \
  --approval-policy never --permission-profile worker)
```

`worker` must already exist in a configuration layer applicable to the supplied
working directory. Threadctl sends its name to app-server; it neither writes
profile files nor lists available names. An unknown name is rejected. A
permission profile is distinct from a general Codex CLI `--profile` and a
native subagent role.

The selected app-server loads applicable configuration for each new root.
The invoking thread's settings, shell aliases, and CLI flags are not inherited.
The requested `--cwd` participates in project configuration discovery and
runtime workspace roots, so a profile tested at the project root needs checking
again for a nested worker directory.

A newly saved applicable profile can be selected for a new root without
restarting the server. Editing its definition does not change an already loaded
worker. Threadctl's creation flags apply only to the new root.

`--approval-policy` controls whether execution can wait for a client decision;
it does not widen filesystem access. The available creation options and their
mutual exclusions are described in [Immediate Thread Control](lifecycle-control.md).

## Checking The Result

JSON `permissionRequest` records the values submitted by threadctl. It is not
the effective runtime policy. Successful creation proves that the server
accepted the request, not that every intended access rule works.

Before relying on a new profile, exercise benign allowed reads and writes,
denied reads, and any required local sockets from the worker. Check that the
worker also receives its intended instructions: restricted filesystem reads can
affect Codex's AGENTS.md discovery and loading.

When the selected profile appears ineffective, check the server's configuration
and launch flags against Codex's documented precedence rules. Legacy
`sandbox_mode` or `--sandbox` settings can take precedence over the named
permission system. Repeating the same creation request does not resolve that
configuration conflict.

## Observed Linux Limitations

Isolated probes on Codex CLI **0.153.2** found the following behavior with
profiles extending `:workspace`:

| Rule shape | Observed result |
| --- | --- |
| Deny an existing directory | Reads inside were denied; unrelated reads worked. |
| Deny an exact regular file or missing path | Sandbox setup failed with a bwrap `Bad file descriptor` error. |
| Deny a parent, then grant a child `read` | The child remained inaccessible. |
| Deny a parent, then grant a child `write` | The child was accessible. |

These are version-specific runtime observations, not alternative permission
semantics. The probes used temporary fixtures through `codex sandbox`; verify
the intended boundary again in the created worker. Granting `write` to repair
a failed read-only exception expands access and is not an equivalent workaround.
