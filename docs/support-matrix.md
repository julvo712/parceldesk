# Supported and verified environments

Build support, a successful container start, and a complete presentation are separate evidence levels. Current release acceptance is recorded in `release/acceptance.json` and local verification reports.

| Component | Selected baseline | Verification / limit |
|---|---|---|
| Development host | macOS Apple Silicon | Initial author environment; Docker Engine 29.4.0 and Compose available |
| Application runtime | Linux ARM64 containers | Initial deployment target; business and telemetry integration tests execute here/on the host as recorded |
| Linux AMD64 | Actual x86_64 containers under Docker Desktop emulation | Four custom images built; observer decoder suite plus six-service runtime, eight business tools, idempotency, authorization, UI/API and a real Anthropic call passed. Physical x86 host and native Cloud guard/eval acceptance remain unverified; see `docs/verification/amd64-runtime.json` |
| Windows | No tested host | Not currently in the validated presenter set; Docker/Linux compatibility alone is not a Windows claim |
| Docker Engine API | v1.45 read endpoints | GET-only container list/stats/logs used by observer, tested against Engine 29.4.0 |
| Container CPU/memory/throttling | Docker Linux VM/Engine counters | Real stats read from all seven scoped running services; throttling fields present on this host. Missing fields on another platform stay absent |
| PostgreSQL | 17.9 image | Durable isolated-schema tests cover business transactions and real lock waits. Exporter is ordinary database monitoring |
| Native Database Observability | Optional | Not established by PostgreSQL exporter metrics; enable/verify separately before showing that product |
| Go | 1.26.4 | Race tests and vet; native HTTP metrics, W3C tracing and profile bridge tested with a real OTLP receiver |
| Python runtime | 3.12 | Provider and SDK availability must match the release compatibility checks |
| Browser | Chromium first | Check accessibility, viewport and interaction reports before asserting other browser support |
| Grafana Cloud | Explicit context and endpoints | Initial stack `demotests_gcloud`; other stacks need their own ingestion credentials, native rules/evaluators and frontend application |
| Coding assistants | Host-installed Codex, Claude Code, Cursor | Each integration requires a real observed session; telemetry field coverage differs by tool |
| Customer identity | Synthetic fixture session | Labelled demo sign-in, not an enterprise authentication implementation |
| Notifications | PostgreSQL sandbox ledger | No actual email or arbitrary network destination |
| Multi-presenter pilot | Two presenters, one clean machine | Pending human execution; required before broad internal rollout |

Production-quality demo means bounded actions, real evidence, polished UX and repeatable operation. It does not imply production customer deployment, universal prompt-injection detection, exact subscription billing, proven human time saved or every OS/browser being validated.
