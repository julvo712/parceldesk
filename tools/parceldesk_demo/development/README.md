# Development ledger and presenter lifecycle

## Runtime integration

`DevelopmentLedger(path).metrics_text()` returns Prometheus text. The host CLI defaults to `runs/development/development.sqlite`. The Mac alone opens this database. SQLite uses WAL, transaction-level allocation checks and a reentrant lock around each connection's public methods. Mutations and close atomically publish `telemetry-snapshot.json` with metrics and a metadata-only event spool. Never point the container at the host SQLite file: WAL shared-memory access across the macOS/Linux bind mount can corrupt it.

`append(event)` accepts immutable `event_id`, `task_id`, `event`, timezone-aware `source_timestamp`, `actor`, optional tool, `evidence_ref`, optional `synthetic`, and `payload`. Supported event names are the eight in the implementation plan. Received time is stored independently. Identical IDs/payloads replay without inserting; conflicting ID reuse fails. Late events are recomputed in source-time order. Session/candidate/commit/PR associations are materialized separately.

`import_session(record, catalog=None)` accepts:

- Required `session_id`, `tool` (`codex`, `claude_code`, `cursor`), `model`, `source_timestamp`, `evidence_ref`.
- Optional `record_id`; use one provider generation ID for generation records. Without it the record ID is session:model, with cumulative usage semantics. `granularity` is `generation` or `cumulative`; mixing them in a session is rejected.
- `usage` has `input`, `output`, `cache_read`, `cache_write`; each is an exact nonnegative integer or null. Normalize input to exclude cache buckets first. Missing data remains null.
- Optional `estimated_cost_usd` and explicit `price_basis`. Otherwise a model-exact catalog entry may estimate known usage. No alias/prefix guessing. Nonzero cache writes with unknown TTL stay unpriced.
- Optional `user`, `repo`, `synthetic`. Exact IDs and dimensions remain in SQLite/log events, not metric labels.

A strictly newer observation can update a cumulative record without double counting; an older observation is ignored, a conflicting same-time observation is rejected, and token counters cannot regress. Session allocations are explicit Decimal fractions in `(0,1]`, total at most one across tasks. Session references without imported usage remain unknown. Accepted/incomplete/unassigned cost categories retain known partial amounts. Full estimated task cost is null while any linked consumption remains unknown.

Supply `event_sink(callable)` to send structured JSON events to the **parceldesk-development** log stream. A durable outbox keeps committed events until the sink succeeds. Delivery is at least once, with stable event IDs. No source transcript is copied. Native coding imports and session records are inputs; the ledger does not launch coding tools or invent historical usage.

## Host CLI

From the repository root:

```bash
PYTHONPATH=tools python -m parceldesk_demo.cli prepare --run meeting-001 --tool codex
PYTHONPATH=tools python -m parceldesk_demo.cli check-diff --run meeting-001
PYTHONPATH=tools python -m parceldesk_demo.cli check-diff --run meeting-001 --reviewed
PYTHONPATH=tools python -m parceldesk_demo.cli evaluate --run meeting-001 --suite smoke
PYTHONPATH=tools python -m parceldesk_demo.cli activate --run meeting-001
PYTHONPATH=tools python -m parceldesk_demo.cli reset --run meeting-001
```

The tested `parceldesk-baseline` Git tag must exist before preparing. `prepare` resolves it to a fixed commit and creates a detached worktree under the already ignored `.worktrees/` directory. The baseline and original checkout are never reset or cleaned. The diff boundary includes only the existing system prompt/context and newly added assertion-bearing regression tests; deletion, rename, stable-code edits, skipped tests, unsafe imports/dynamic execution and symlinks are rejected. Reviewing records the exact diff hash. A subsequent edit invalidates review.

Candidate bytes are copied to immutable `runs/development/packages/<agent_version>`. Version hashing matches the runtime exactly: SHA-256 of system prompt, null byte and context module, truncated to 16 hex characters. The copied bytes and exact evaluation-report digest are checked before activation.

The default evaluator runs the real `evals/runner.py` inside the project-scoped agent-api container. Only the immutable package and evidence paths under the mounted `/app/runs` are passed. A custom host argv adapter may be supplied using `--evaluator`; no shell is invoked and no web endpoint should execute these commands.

After evaluation, **host gcx** reads the native experiment report through `demotests_gcloud`. The candidate version, experiment status, ready state, exact trial IDs/count, primary-verdict coverage, evaluator identity and each final score must match. Native read credentials never enter the container. Missing/pending native results cannot activate a candidate. Local completed rejection (exit 2) is retained as a rejected candidate rather than discarded as a tool error. Smoke reports need six completed trials and full reports need 36.

`activate` writes `runs/development/active.json`; the runtime must consume this manifest only for new conversations and retain existing conversation packages. `reset` writes a baseline selection and preserves every worktree, candidate, report and event. It does not restart containers itself.

One immutable completed verdict is recorded per candidate version. A contradictory repeated verdict is rejected; use a newly changed candidate for a new acceptance decision. This avoids silently relabelling historical failures.

## Explicit session linking

```bash
PYTHONPATH=tools python -m parceldesk_demo.cli link-session \
  --task demo:meeting-001 --conversation REAL-CONVERSATION-ID \
  --allocation 1 --tool codex --evidence-ref REAL-SOURCE-REFERENCE
```

Retries use a stable event ID derived from the arguments. For a deliberate later allocation revision, supply a new `--event-id` and actual `--source-timestamp`. `import-sessions --file` accepts a normalized record, list, or `{records:[...]}` document. `append-event --file` accepts an explicit event. These commands never infer a PR association or publish repositories.

## Tests and source parity

```bash
PYTHONPATH=tools PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tools/tests -v
PYTHONPATH=tools python -m parceldesk_demo.cli export-expectations > runs/development/expected.json
python infra/grafana/verify_values.py --expected runs/development/expected.json
```

Tests use disposable SQLite databases and Git repositories. Their native reports are explicit test doubles; they are never imported into the demo's metrics. Source export hashes the authentic event/session snapshot and produces Cloud scalar expectations. Exporter time series represent observation time; task elapsed time comes from source timestamps. Productivity metrics do not claim human time saved or causal coding-tool superiority.

The dated Anthropic prices in `pricing-catalog.json` were checked against the [official pricing table](https://platform.claude.com/docs/en/about-claude/pricing) on 2026-09-15. They are standard global API-equivalent token rates, not subscription charges, negotiated terms or regional/fast/batch rates.

## Evaluation-report telemetry and separate log resource

`parceldesk_demo.telemetry.configure_development_snapshot()` returns `(collector, log_exporter)` for the API lifespan. Add `collector.metrics_text()` to the metrics response, periodically call `collector.flush_outbox()`, and shut down both objects at application shutdown. The API reads the host snapshot only; its evaluation cache and spool receipts live in `/data/telemetry/evaluations.sqlite` on a Docker named volume. The exporter has its own OpenTelemetry LoggerProvider and `service.name=parceldesk-development`; it does not replace global application providers.

The collector reads actual local/native report files, caches minimal normalized evidence in SQLite, deduplicates copies by experiment/trial/check, and prefers native evidence. Verifier version, suite version and local/native source are separate metric labels. Old verifier 1 results are not combined into verifier 2 scores. Missing version is `unknown`, never inferred from today's source code. Report running/errored/pending-native states are exported separately from observed trial verdicts. A malformed rewrite retains the previous valid observation while exposing a read error.

Evaluation subprocess Prometheus registries are not served by the long-running API. Accordingly, report-derived native token/cost totals have separate `parceldesk_evaluation_tokens_total` and `parceldesk_evaluation_cost_usd` families with explicit coverage. They are not inserted into live API LLM counters or labelled as judge billing. Cache breakdown unavailable in native total tokens is not invented.

Freeze source expectations after imports and a completed native readback, allow Cloud to receive the next scrape, then compare:

```bash
PYTHONPATH=tools python -m parceldesk_demo.telemetry \
  --ledger runs/development/development.sqlite --reports runs \
  --output runs/development/source-expectations.json
python infra/grafana/verify_values.py --expected runs/development/source-expectations.json
```

This includes genuine task inventory, per-tool sessions, token buckets, known consumption, price coverage and primary verdict counts by verifier/source. Unknown cost has no fabricated zero expectation. Native report `pass_denominator` counts test cases, while `completed_count` counts trials; host verification examines every unique trial's primary verdict directly.
