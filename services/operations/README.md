# ParcelDesk operations and carrier

Durable business enforcement for the demo. Go 1.26, PostgreSQL 17, native OTel HTTP/SQL traces and HTTP metrics, Pyroscope CPU/memory profiles with the trace/span bridge. All outbound notification effects are PostgreSQL sandbox records; this service has no SMTP sender.

## Run

The top-level Docker Compose supplies `DATABASE_URL`, `INTERNAL_SERVICE_TOKEN`, `CARRIER_URL`, `OTEL_EXPORTER_OTLP_ENDPOINT` and `PYROSCOPE_SERVER_ADDRESS`. `operations` listens on 8080; override the image entrypoint to `/usr/local/bin/carrier` for the carrier service on 8081. Neither internal service is intended to be exposed outside the Compose network.

`GET /health/live` checks process health. `GET /health/ready` checks the operations database (carrier has no database). All `/internal/` endpoints require `X-Service-Token`. Request bodies are capped at 1 MiB; malformed/unknown envelope fields are rejected.

Startup applies embedded idempotent migrations under a PostgreSQL advisory lock. Restart resets leases belonging to the old single operations process. Shutdown cancels load and rolls back fault locks before closing the pool.

## Internal contract

`POST /internal/tools/{name}` accepts:

```json
{"context":{"demo_run_id":"run-1","conversation_id":"conversation-1","customer_id":"C1","business_date":"2026-09-15","fixture_revision":"store-v1","agent_version":"baseline","traffic_kind":"runtime","scenario":"healthy"},"arguments":{"order_id":"PD-1042"},"call_id":"call-1"}
```

The response is `{ "call_id": "call-1", "status": "ok", "data": {...} }`. Status is `ok`, `policy_denied`, `invalid` or `failed`. Fault state comes from the persisted, expiring lease; the caller's `scenario` cannot bypass it.

| Tool | Arguments | Key result |
|---|---|---|
| `get_order` | `order_id` | `id`, `customer_email`, `eligible`, `available_stock`, source revision |
| `get_retailer_policy` | none | trusted policy content |
| `get_supplier_guide` | `order_id` | untrusted content; injected fixture under active lease |
| `check_inventory` | `order_id` | `available`, `quantity`, SKU |
| `get_shipping_options` | `order_id`, optional `requested_by` ISO date | mapped `arrival_date`, independent `raw_carrier`, `deadline_met` |
| `propose_replacement` | `order_id`, optional `requested_by` | persisted `proposal_id`, arrival, raw carrier, confirmation requirement |
| `create_replacement` | `proposal_id`, `idempotency_key` | persisted `replacement_id`; requires confirmed own-conversation proposal |
| `send_confirmation` | `replacement_id`, `to`, `idempotency_key`, optional `body` | `notification_id`, `sandbox:true`, `recorded:true`, `delivered:false` |

A model-supplied notification body is never sent or trusted: the sandbox stores stable service-generated confirmation copy. The recipient must exactly match the stored customer's email.

### Persistence endpoints

- `POST /internal/runs`: `{run_id?,customer_id?,business_date?,scenario?,fixture_revision?}`. Defaults C1 / 2026-09-15. Duplicate run initialization must retain the original customer and date.
- `GET /internal/runs/{id}`: current run and effective scenario.
- `GET /internal/orders?run_id=...&customer_id=...`: `{orders:[...]}`.
- `POST /internal/conversations`: `{run_id,customer_id,order_id,conversation_id?,agent_version?}`. Returns durable row with `id` and JSON `state`.
- `GET /internal/conversations/{id}?run_id=...&customer_id=...`: same row.
- `PUT /internal/conversations/{id}/state`: `{run_id,customer_id,state:{...}}`; Python controls the persisted chat/event schema. Caller serializes turns per conversation.
- `GET /internal/proposals/{id}?run_id=...&customer_id=...`: authenticated proposal row, including `conversation_id` and `order_id`.
- `POST /internal/proposals/{id}/confirm`: `{context:{...},idempotency_key}`. This endpoint is called only after explicit browser confirmation by the trusted Python API, never exposed as an LLM tool.
- `POST /internal/sessions`: `{id?,run_id,customer_id,ttl_seconds?}`; defaults four hours, bounded to one day. Returns opaque UUID and expiry.
- `GET /internal/sessions/{id}`: session, or 401 if expired/missing.
- `POST /internal/runs/{id}/attempts`: `{conversation_id,call_id,tool_name,status,reason,trace_id}` records gateway denials/unavailability before dispatch.
- `GET /internal/runs/{id}/evidence`: full proposals, confirmations, replacements, notifications, attempts and carrier quotes, with `_count` fields. Synthetic fixture data only.

### Fixtures

C1 / Maya Chen / `maya.chen@example.test` owns PD-1042 (healthy Arc headphones), PD-1043 (expired Arc), PD-1044 (Move speaker, no stock), PD-1045 (Loop earbuds, late delivery). C2 / Alex Morgan owns PD-2042. Mutable state is run-scoped. Eligibility is damaged product with delivery age 0–30 days inclusive.

### Failure leases

`POST /internal/runs/{id}/scenario` with `{scenario,ttl_seconds}` activates one scenario for 1–300 seconds. `DELETE` on the same URL cancels and waits for recovery. `db_lock` owns a dedicated transaction locking ARC-01 stock; inventory's locking read genuinely waits. `cpu_regression` executes bounded SHA256 work in the inventory request. `cpu_pressure` runs bounded CPU work for the lease lifetime; Compose must impose the documented one-CPU quota. `shipping_mapping_bug` subtracts three days from the adapter date while preserving raw carrier response evidence. Injection substitutes only the active run's returned supplier guide. Python implements its own relevant leases using the same effective scenario. `GET /internal/cpu-probe?duration_ms=600` provides a 100–3000 ms CPU/span-profile probe.

## Test

```sh
TEST_DATABASE_URL='postgres://postgres:password@127.0.0.1:5432/parceldesk?sslmode=disable' go test -race ./...
```

Integration tests create and remove a UUID-named PostgreSQL schema for each test. They verify cross-customer rejection, eligibility day boundaries, stock, explicit confirmation, 20 concurrent exactly-once action retries, recipient matching, actual PostgreSQL lock waiter evidence, cancellation/TTL, and raw-vs-mapped carrier dates. Without `TEST_DATABASE_URL`, database tests explicitly skip; this is not a complete acceptance run.

Telemetry configuration follows [Grafana Go span profiles](https://grafana.com/docs/pyroscope/latest/configure-client/trace-span-profiles/go-span-profiles/). Profile application/service labels match OTel `service.name`. SQL spans record operation names and database namespace, never bind values or interpolated query content. Tool metrics have only bounded tool/outcome labels; run/conversation IDs remain on spans and logs.
