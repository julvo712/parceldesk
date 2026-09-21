# ParcelDesk observability demo

ParcelDesk is a fictional retailer support application with a Python LLM agent,
a Go operations service, PostgreSQL and a React frontend. It runs in local Docker
and exports application, agent and infrastructure telemetry to Grafana Cloud.

This public repository starts from a scanned source snapshot. Local credentials,
recordings, captured conversations, dashboard backups and the private development
history are excluded. The fixture customers and orders are fictional.

The [observability foundation](docs/observability-foundation.md) adds versioned continuous profiling and direct GitHub
reporting. Older presenter documents describe the previous demo; its custom
candidate ledger is not a native productivity feature and is not used by the new
AI investment and delivery dashboard.

## Development

- `make test`: backend, frontend and supporting checks.
- `make test-browser`: browser interaction checks.
- `make acceptance`: full automated acceptance, including a disposable test database.
- `make install CLOUD_CONFIG=/path/to/cloud-config.json`: configure a local stack.

Credentials belong in `.secrets/` and must never be committed. Copy and adapt
`release/cloud-config.example.json` for your own Grafana Cloud endpoints. The Faro
collector key is a placeholder until you configure your own frontend application.

See [installation](docs/install.md), [architecture](docs/design.md) and
[recovery](docs/recovery.md). Telemetry shown in Grafana must come from real runs.
