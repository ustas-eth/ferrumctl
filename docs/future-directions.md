# Future Directions

This is a working list of unimplemented feature ideas. Remove entries when they
are implemented or no longer worth pursuing.

Ferrumctl should remain a set of narrow Unix controls for Codex state, not an
orchestration framework. Prefer features that expose a recurring coordination
need that native handles, app-server methods, or ordinary shell tools do not
already solve cleanly.

## Near-Term Ideas

- **Multi-thread observation:** inspect several workers in one compact request,
  including loaded state, active flags, goal status, context pressure, current
  turn, and recent activity.
- **Thread predicates:** expose loaded state, thread status, active flags,
  context remaining, and activity age through exit status for shell and
  wakectl composition. Avoid a general `stalled` judgment.
- **Background-terminal completion wakes:** let wakectl observe one exact
  terminal using its process and originating item identities, covering work
  that outlives its agent turn.
- **Runner status:** report whether the installed wakectl runner is active,
  when it last ran, and when it should run next.
- **Wake-job provenance:** record the creating thread when `CODEX_THREAD_ID` is
  available and support filtering the shared queue by it. Treat this as
  provenance, not authorization.

## Later Ideas

- **External compaction:** reconsider a guarded threadctl command for long-lived
  workers. Codex exposes `thread/compact/start`, but it has no atomic idle
  precondition; ownership, races, and completion reporting need a sound design.
- **Notification-driven observation:** investigate app-server notifications if
  runner polling becomes a measured latency or scaling problem. A persistent
  subscriber would also need reconnect, replay, and lifecycle semantics.
- **Additional thread lifecycle controls:** consider archive, fork, and naming
  only after concrete host-control workflows demonstrate their value.

## Boundaries

- Do not add an umbrella command, task graph, worker scheduler, automatic
  approval policy, or generic stalled-agent detector.
- Do not wrap native subagent operations when the current session owns the live
  handle.
- Prefer read-only observation improvements first. Add stateful coordination
  only after ownership, retry, and cleanup behavior is understood.
