# Presenter recovery

## First response

Keep the customer outcome separate from the diagnostic evidence. A failure is part of the demonstration only when the selected scenario explains it. An unrelated outage remains an outage.

1. Read `http://localhost:3101` for the active run and lease.
2. Reset the scenario. Fault TTL is at most five minutes; manual reset should release the real database lock/CPU load promptly.
3. Run `python3 release/manage.py doctor --context demotests_gcloud`.
4. Start a fresh session/run and repeat one benign replacement. Existing completed replacements remain idempotent; a fresh run avoids confusing a successful prior action with a new one.

## Common cases

| Symptom | Check | Recovery |
|---|---|---|
| Browser cannot load | Docker project services and port 3100 | Restore the web service; avoid restarting unrelated local projects |
| Chat reports safety service unavailable | Guard transport/native access and active `guard_unavailable` lease | Reset the lease or restore real guard connectivity; never change fail-closed behavior to make the demo continue |
| Model is slow or quota limited | Provider status, configured model and generation error | Explain the live failure; use a labelled saved real run if available, or skip the chapter |
| Blocked supplier attempt | Native rule ID, proposed tool arguments, denied action ledger | This is an expected security outcome; investigate the agent behavior and run the candidate comparison |
| No metrics/logs in Cloud | Alloy health, exporter status, secret scopes, correct selected context | Fix ingestion and wait for fresh observations; an empty query is not proof of zero errors |
| No CPU profile for a SQL wait | Confirm whether the trace is waiting or doing CPU work | Use `cpu_regression` or the CPU probe for sampled CPU evidence; a lock wait need not consume CPU |
| Observer shows stale data | Observer health and Docker socket availability | Restore the observer; keep the socket confined to it, never mount it into application services |
| PostgreSQL exporter reports `pg_up=0` | Monitor role, password mount and Alloy exporter logs | Reapply `tools/observer/provision-monitor.sql` through the project PostgreSQL container |
| Candidate experiment is still pending | Native trial/evaluator terminal status and deadline | Display pending/incomplete. Do not count it as passed or silently switch to a saved score |
| Customer clicks confirmation twice | Persisted proposal and idempotency key | Refresh persisted state; the business ledger must contain one replacement/notification |

## Project-scoped inspection

```sh
docker compose --project-name parceldesk --file compose.yaml ps
docker compose --project-name parceldesk --file compose.yaml logs --tail 80 operations carrier observer alloy
```

If installation created an override, prefer the release manager or include the override path recorded in `runs/install/state.json`. Do not dump `.env`, mounted secret files or complete container environment variables into a support ticket.

## Logs and metrics ownership

Go operations/carrier structured stdout is collected once by the observer and forwarded through Alloy's Loki receiver. Python application logs use OTLP directly and are excluded from observer shipping. The observer polls only the Compose project and exposes measured Engine counters; this is not a macOS host monitoring agent. A socket mounted `:ro` does not enforce Docker API permissions: the dedicated collector enforces fixed GET-only API paths and exposes no Docker proxy.
