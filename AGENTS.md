# ParcelDesk demo
During the original prompt-only live exercise, change only agents/replacement/system.md, agents/replacement/context.py and new local regression tests. Do not alter stable business rules, guards, evaluators, fixtures or observability to make a candidate pass. Explicitly requested foundation work is exempt from that edit restriction.
Use the approved docs/design.md contract. Never fabricate telemetry or evaluator results. Keep secrets in .secrets (0600) and never in git. Every gcx command targets --context demotests_gcloud. Docker operations must name this project's compose file/project. No external notifications. No subagents without explicit task authorization.

For the native profiling and GitHub foundation, follow docs/observability-foundation.md.
Before a performance change, inspect the running service version, query profiles
through gcx, and relate hotspots to that exact Git commit. After a change, rerun
the same load and compare absolute CPU/memory and customer latency. Use native
Profiles Drilldown for the flamegraph diff. A relative flamegraph change alone
does not establish an absolute resource regression.

Do not read .secrets or raw gcx config. Use the configured host CLI credentials.
Code quality here means measured runtime behavior, not an invented code score.
Delivery metrics come directly from GitHub, never from the local candidate ledger.
