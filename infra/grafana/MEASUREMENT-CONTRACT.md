# ParcelDesk dashboard measurement contract

## Ownership and deployment

The initial target is `demotests_gcloud`, `https://demotests.grafana.net/`. Folder `parceldesk-demo` and the seven UIDs in `manifest.json` are exclusively owned by this project. Every mutation uses gcx, explicit context, validated native v2 resources, supported dry-run and independent readback. Credentials are never read from raw gcx configuration or written to project files. `generate.py` accepts alternate datasource UIDs for another installation.

Native schemas were discovered live on 2026-09-15. The installed CLI returns “No example available” for dashboards and folders. `resources list-types dashboards` exposes only root schema with unresolved component references, so the full **read-only** OpenAPI document was fetched via `gcx api /openapi/v3/apis/dashboard.grafana.app/v2`; no dedicated gcx operation exposes these references. Authoring uses `Panel`, `QueryGroup`, `PanelQuery`, `DataQuery`, `VizConfig`, `GridLayout` and `CustomVariable` kinds from that schema. Empty optional `fieldConfig.defaults.mappings` is omitted by the server; the source uses a non-empty null mapping. No spec differences are discarded during verification.

## Every panel follows these rules

- A missing metric, unknown cost, unevaluated case or unavailable integration is **not zero**. No `or vector(0)` fallback is allowed. A query error remains a Grafana panel error.
- A null/empty observation is rendered in neutral gray, not as a healthy green result. A measured zero is a numerical zero.
- Runtime counter panels use the selected range or rate interval. Counter rates require at least two scrapes. Histograms show observed latency, not vendor service guarantees.
- Coding/development panels are **ledger inventory snapshots at the selected end time**. Their time series show exporter observation time. Importing an old session does not recreate its historical Prometheus time series.
- `traffic_kind`: `runtime`, `experiment`, `probe`. The variable filters turn and LLM panels. Guard, evaluation and business metrics currently have their own supplied schemas without this dimension; their panel descriptions and grouping retain that scope.
- Tool selector values: `codex`, `claude_code`, `cursor`. No developer count is inferred from tool count. Delivery task counts remain whole-ledger counts; the tool selector applies to allocated consumption only and does not fabricate per-tool task ownership.
- Exact session, task, commit, PR, trace and experiment IDs belong in the durable ledger and structured logs. They are not Prometheus labels.

## Metrics

| Family | Type / labels | Meaning |
|---|---|---|
| `parceldesk_http_requests_total` | Counter: service, method, status | Handled API requests. 5xx fraction uses observed requests as denominator. |
| `parceldesk_turns_total` | Counter: outcome, traffic_kind | Completed agent turns, grouped by real outcome. |
| `parceldesk_llm_tokens_total` | Counter: provider, model, type, traffic_kind | Provider-reported normalized usage. Missing usage is unknown. |
| `parceldesk_llm_duration_seconds` | Histogram: provider, model, traffic_kind | Observed end-to-end generation duration, including explicitly injected boundary delay when enabled. |
| `parceldesk_guard_decisions_total` | Counter: action, source | Actual local/native guard decisions. Denial and unavailability must have distinct actions. |
| `parceldesk_tool_calls_total` | Counter: tool, status | Actual tool attempt/status. An unsafe proposal blocked before dispatch is not a successful business action. |
| `parceldesk_evaluations_total` | Counter: check, result, version | Executed deterministic checks. `pass` is explicit. Sample count counts checks, not unique conversations. Native pending/error judge results must not increment pass. |
| `parceldesk_coding_sessions` | Gauge: tool | Number of unique genuine source sessions in the importer ledger. |
| `parceldesk_coding_tokens_total` | Persisted counter: tool, model, type | Deduplicated observed source usage; input, output, cached input and cache write are separate types. |
| `parceldesk_coding_cost_usd` | Gauge: tool, model | Known priced API-equivalent consumption in the ledger. Not billed subscription cost. |
| `parceldesk_coding_price_coverage` | Gauge 0–1: tool | Fraction of source records with a usable model/usage/pricing basis; exporter must document exact denominator. Missing denominator is unknown. |
| `parceldesk_development_tasks` | Gauge: state | Durable task inventory. Accepted/unfinished work is explicit. |
| `parceldesk_development_accepted_duration_seconds` | Persisted histogram | Actual elapsed start→acceptance time, including rejected attempts. No accepted tasks means no duration. |
| `parceldesk_development_candidates_total` | Persisted counter: outcome | Evaluated candidate outcomes, deduplicated by durable event ID. |
| `parceldesk_development_tasks_first_pass_total` | Persisted counter | Accepted tasks whose first evaluated candidate passed. Divide by accepted tasks; zero accepted tasks yields undefined. |
| `parceldesk_development_cost_usd` | Gauge: tool, coverage | Explicitly allocated known consumption. `accepted` denotes accepted-task allocations; incomplete and unassigned categories remain visible. |
| `parceldesk_build_info` | Info gauge: version | Active application/prompt version, value 1. |
| `parceldesk_signal_last_seen_seconds` | Gauge: signal | Actual last observation timestamp. Never “now” unless a real observation occurred. |
| `parceldesk_scenario_active` | Gauge: scenario | Leased scenario state, measured 0/1. |
| `parceldesk_scenario_expires_seconds` | Gauge | Real UTC lease expiry timestamp. |
| `parceldesk_last_reset_timestamp_seconds` | Gauge | Successful reset timestamp. |
| `up`, `process_*` | Standard scrape/process families | Scoped to jobs prefixed `parceldesk`. A Python process RSS/CPU panel is not Docker VM or host utilization. |

Readiness metric families above are producer contracts. Their absence remains visible until the runtime actually implements them. Do not claim the dashboard generator itself measures them.

## Financial and productivity interpretation

Estimated cost uses a versioned price registry and exact normalized usage. Cache input is not charged a second time as uncached input. Models lacking an approved mapping remain unknown. Actual seat spend is displayed only if supplied independently, with a distinct label; this release does not infer invoices.

Per-session consumption, repository, user and task relationships are shown as exact source events in the evidence panels. If those source fields were unavailable, the dashboard cannot reconstruct them. No fabricated “top expensive sessions” or session-to-PR relationship is computed from aggregate model counters.

The acceptance-cost panel divides known consumption explicitly allocated to accepted tasks by the number of accepted tasks. It must be read together with pricing and attribution coverage. It is not a fully loaded development cost. First-pass acceptance is task-based and cannot be calculated by dividing accepted candidate events by all candidate events.

## Structured Loki event contract

Runtime stream: `{service_name="parceldesk-agent"}`. Coding/task stream: `{service_name="parceldesk-development"}`. Events use JSON `event`, `observed_at`, `source_timestamp`, `tool` (when known), evidence IDs and relevant structured values.

Coding: `coding_session_imported`, `coding_import_failed`, `session_linked`.
Development: `task_started`, `session_linked`, `candidate_submitted`, `candidate_evaluated`, `candidate_accepted`, `task_closed`, `commit_linked`, `pr_observed`.
Runtime: `evaluation_completed`, `guard_decision`, `doctor_completed`, `scenario_activated`, `scenario_expired`, `scenario_reset`, `reset_completed`.

Each event retains its authentic provenance. Source transcripts and arbitrary local files are not emitted wholesale. Demo app payloads use synthetic customer data.

## Verification levels

1. **Schema / deployment**: all eight resources validate, dry-run and push; all seven live specs and folder annotations match the manifests exactly.
2. **Query syntax**: every concrete PromQL and LogQL query succeeds after macro expansion. Empty results do not pass the next level.
3. **Source parity**: freeze an authentic ledger snapshot, supply expected values to `verify_values.py`, and compare its aggregates with Grafana Cloud values. Missing telemetry or expected source evidence does not pass. A measured zero can pass when the genuine source supports it, such as zero first-pass acceptances after rejected work.
4. **Visual**: render and inspect all seven full dashboards at 1440px; check variables, zero-data window and a missing-price source. Rerender after correcting truncation or misleading colors.
5. **Native drilldowns**: traverse trace/profile, browser app, Agent Observability guard and experiment links from actual evidence. Plugin installation alone is not a successful trace/profile correlation.

The deployment and query scripts report each level separately. Never rename successful schema validation to production acceptance.

## Producer alignment verified during implementation

Live discovery confirmed Python API `http_server_duration_milliseconds_*` with `http_target`, and Go `http_server_request_duration_seconds_*` with `http_route`; the API panel converts milliseconds to seconds and both exclude non-customer health traffic where applicable. Business tool histograms use `tool_name` and `outcome`. Container metrics are produced by the dedicated observer with `project="parceldesk"` and `compose_service`; actual CPU, working-set memory and throttled seconds are plotted. PostgreSQL lock/long-transaction metrics are scoped by `service_name="parceldesk-postgres"`.

Evaluation telemetry now comes from `tools/parceldesk_demo/telemetry.py`. `parceldesk_evaluations_total` additionally carries `evaluator_version`, `suite_version` and `source`. The primary check normalizes native `final` and local `primary_passed` to `primary_verdict`. Headline quality uses **primary trial verdicts**, rather than averaging easy diagnostic checks into the primary success rate. Every quality breakdown separates evaluator versions. Verifier 1 is retained as legacy evidence; verifier 2 uses the corrected persisted-record contract. Missing local evaluator version remains unknown until native readback.

`parceldesk_evaluation_reports` exposes report status/source; pending and errored are not completed success. `parceldesk_evaluation_report_last_seen_seconds` comes from the actual native completion/update timestamp or local file observation. Known evaluation cost and total tokens use dedicated `parceldesk_evaluation_cost_usd` and `parceldesk_evaluation_tokens_total` families. Coverage remains explicit; native total tokens do not invent an input/cache breakdown. Evaluation subprocesses do not share the API's Prometheus registry, so report-derived consumption is not merged into live API `parceldesk_llm_*` counters.

A zero numerator is used only when a real measured denominator exists: API error fraction and primary pass fraction use `numerator or (0 * measured_denominator)` and require a positive denominator. They never manufacture a healthy zero from an absent telemetry source.

Development data crosses the Mac/Linux boundary as an atomic JSON snapshot of
Prometheus text and a metadata event spool. The API never opens the host SQLite
database. `parceldesk_development_snapshot_read_error` exposes read failures and
`parceldesk_development_snapshot_published_seconds` exposes actual publication
time; an idle developer does not imply a failed collector. Each distinct native
evaluation experiment contributes a candidate outcome, including repeated
evaluations of identical prompt bytes on different models. Acceptance selects an
exact passing experiment and binds its provider/model/verifier/suite provenance.

Evaluation checks and report inventory also carry `provider`, `model` and
`evaluation_suite`. Prompt comparisons retain those dimensions; the quality
page defaults to the accepted model and full suite. Heldout trials are separate
from the full-suite denominator. `unknown` suite/model metadata is never inferred
from trial counts. Source parity now checks prompt, model and suite explicitly.
