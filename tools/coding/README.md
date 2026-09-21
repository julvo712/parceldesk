# Authentic coding consumption

`launch.sh` starts the installed coding-agent telemetry wrapper. Import only
explicitly selected native conversation readbacks; the importer never scans a
developer's history or automatically associates activity with an outcome.

```sh
python3 tools/coding/import_native.py runs/coding-claude-native.json \
  runs/coding-codex-native.json runs/coding-cursor-native.json \
  --ledger runs/development/development.sqlite
```

Use `--dry-run` to validate without writing. Native generation IDs deduplicate
replays. Native source time is preserved; ingestion time is separate. Use the
development CLI's explicit `link-session` command to allocate each conversation
to a task. A coding session is consumption evidence, not an accepted change.

## Token and pricing contract

| Source | Exclusive input | Cache reads/writes | Missing fields |
| --- | --- | --- | --- |
| OpenAI / Codex | Native input minus native cached reads | Retained separately | Unknown; missing reads also make exclusive input unknown |
| Anthropic / Claude Code | Native input already excludes caches | Retained separately | Unknown |
| Cursor provider, including `auto-smart` | Unknown overlap contract, omitted from normalized input | Retained when present | Unknown |

Reasoning and total tokens overlap existing buckets and are never added again.
Raw source JSON remains the authoritative record of reported counts. Cursor's
[official Grafana mapper](https://github.com/grafana/agento11y/blob/db6d03eca13551d03a6ca15ecd627eead4ed542a/plugins/agento11y/internal/agents/cursor/mapper/mapper.go#L500)
copies hook input/cache fields directly. The
[Cursor hook documentation](https://cursor.com/docs/hooks) does not establish
their overlap semantics. The importer therefore does not guess a normalized
input value or an underlying model behind Cursor's routing name.

Explicit native USD fields carry `native-reported-usd:<field>` provenance. An
optional `--catalog` must name an exact model and provenance-backed prices; all
required token buckets and rates must be known. Unknown cost stays null, with
price coverage below 100%. Catalog prices are API-equivalent estimates and do
not represent coding-tool subscriptions or invoices.

## Claude cache-TTL enrichment

Native protobuf JSON can omit an explicit zero bucket and omits cache TTL detail.
For one selected Claude conversation, the following joins native generations to
the local source's usage metadata by exact model/input/output/cache-write tuple.
It requires a unique match for every generation and deduplicates repeated
message blocks by message ID.

```sh
python3 tools/coding/enrich_claude_usage.py \
  --native runs/coding-claude-native.json \
  --claude-jsonl /explicit/path/CONVERSATION_ID.jsonl \
  --ledger runs/development/development.sqlite
```

The script never emits prompt, response or tool text. It requires explicit
standard/global pricing metadata and cache writes split by 5-minute/1-hour TTL.
It records the source SHA-256, message/native-generation identity, TTL counts,
pricing URL/date and exact Decimal rates. The current verified price snapshot
supports Sonnet 5 only. Refresh its rates against
[official Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing)
before using it after pricing changes.

Enrichment fills unknown fields only, preserves known counts and original native
timestamps, and saves an immutable before/after audit. Reimporting the original
native JSON cannot erase enriched metadata or double-count tokens. API-equivalent
token cost remains separate from seat spending, request fees and any unknown
consumption from other tools.

## Independent Cloud verification

```sh
PYTHONPATH=tools python3 -m parceldesk_demo.telemetry \
  --ledger runs/development/development.sqlite --reports runs \
  --output runs/development/source-expectations.json
python3 infra/grafana/verify_values.py \
  --expected runs/development/source-expectations.json
```

This compares actual persisted records with independently queried Cloud scalar
values. A rendered panel or successful HTTP import alone is not verification.

## Host and container storage boundary

The Mac exclusively owns `development.sqlite`. Each host mutation and close
atomically publishes `telemetry-snapshot.json`: Prometheus exposition plus an
append-only metadata event spool. The API reads this immutable snapshot and
exports its records under `service.name=parceldesk-development`.

The API never opens the host SQLite database. Its evaluation-report cache and
event receipts live on the Docker named volume `agent-telemetry-data`, at
`/data/telemetry/evaluations.sqlite`. This avoids SQLite WAL shared-memory access
across the macOS/Linux bind-mount boundary. Event IDs support replay deduplication;
a crash before a receipt is committed can repeat a log event. Local exporter
flush acknowledgment is separate from independent Cloud readback verification.

Missing snapshots do not produce fake task counts. An unreadable update retains
the last complete snapshot and exposes `parceldesk_development_snapshot_read_error`;
`parceldesk_development_snapshot_published_seconds` shows its actual freshness.

## Host setup and verified sessions

Codex requires explicit trust for the official plugin hooks in its supported TUI before automatic export begins. The initial rehearsal imported only selected project sessions; a subsequent real Codex session verified automatic hook export. A plugin being installed is not sufficient evidence of delivery.

Cursor used its authenticated desktop application for the explicitly approved review of `agents/replacement/system.md` and `context.py`. The separate Cursor CLI was not authenticated and was not used for that review. Cursor's global hook commands pass through `scoped_hook.py`: it forwards only events whose workspace roots/cwd all resolve inside this project. Missing, mixed, outside and symlink-escaped roots are excluded. Scope-filter tests pass; the final filtering change has not had another live desktop review. Recheck native session delivery before presenting on a new host.

Claude Code's genuine review was joined to native generations using usage metadata only. Neither installation nor imported records are presented as evidence of a human presenter completing the coding workflow. See [release verification](../../docs/release-verification.md) for session totals and price coverage.
