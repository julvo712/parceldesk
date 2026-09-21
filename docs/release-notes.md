# ParcelDesk 0.1.0 — internal release candidate

Default inference uses the explicitly selected Anthropic `claude-sonnet-4-5-20250929` model and a funded provider key. Other providers require an explicit profile choice; there is no automatic fallback.

## Included

- Local Docker application and a separate carrier/operations business service with PostgreSQL persistence.
- Eight guarded tools, explicit persisted confirmation and exactly-once sandbox actions.
- Coding-agent FinOps/activity and measured development-outcome dashboards alongside agent quality, runtime and readiness dashboards, deployed through gcx.
- Native Agent Observability generation, hook and evaluation integration; ordinary browser/backend/database/container signals in the same Grafana Cloud stack.
- Real bounded fault scenarios, including database locking, CPU work/pressure and application shipping-date mapping.
- Project-scoped Docker statistics and operations/carrier stdout collection; read-only PostgreSQL monitoring role.
- Deterministic, scanned source bundles; platform-specific OCI image build commands; install/doctor, source/image/database snapshots, upgrade/rollback and owned-project removal.
- Presenter, installation and recovery documentation.

## Evidence and remaining rollout gates

Business service race tests and vet pass, including 20 simultaneous idempotent action retries and a real PostgreSQL lock waiter. The observer's cgroup/frame decoding and retry/dedup tests pass; direct Engine collection confirms CPU/memory/throttling counters for the running project on the initial host. Release tests cover deterministic archives, secret exclusion, member/checksum validation and scoped uninstall.

The initial ARM64 host also passed the real browser/native telemetry journey, same-model prompt evaluation improvement from33/36 to36/36, and all seven dashboard readbacks. See [release verification](release-verification.md) for exact evidence and scope. An isolated AMD64 runtime smoke under Docker Desktop emulation passed; physical x86-host validation and the two-presenter pilot (one clean machine) remain pending before broad internal rollout. `release/acceptance.json` is the explicit gate record.

No real customer notifications are sent. Pricing is estimated consumption with visible coverage; coding metrics are measured activity/task outcomes, not a causal productivity or human-time-saved claim.

## Ownership

Initial demo owner: Julius Vogt. Assign a maintainer and internal support/distribution channel before broader rollout. The tooling prepares local artifacts and never publishes or messages an audience automatically.

## Repeatable release verification

`make acceptance` / `make release-check` now writes an actual per-component result to `runs/release-check.json`, including credential scanning, Go tests against an isolated PostgreSQL database, Python contracts, web build/unit tests, observer/release tests and the Playwright suite. The GitHub Actions definition runs those checks without production credentials and uploads the report and browser artifacts. The workflow definition is supplied; a hosted GitHub run must be recorded after publishing the repository. Native Cloud/provider acceptance and the human pilot remain explicit separate gates.

Fresh source downloads initialize their own Git baseline after the credential scan. First launch uses the shipped, hash-checked validated reference for the selected model; recurring coding starts from the weaker baseline surface. Existing repositories and activations are preserved.
