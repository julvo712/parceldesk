# Observability foundation

## Data paths

```text
Claude Code / Codex / Cursor -> official agento11y integration -> Grafana Cloud
Python / Go -> Pyroscope SDK -> local Alloy -> Grafana Cloud Profiles
Python / Go -> OpenTelemetry -> local Alloy -> metrics, logs and traces
Browser -> Faro -> configured Grafana Cloud Frontend Observability collector
GitHub API <-> Grafana GitHub data source (no Alloy or custom exporter)
```

The public source lives at https://github.com/julvo712/parceldesk. The original
local checkout and its private history remain separate. Use this public checkout
for the new development workflow. Do not start two copies of the `parceldesk`
Compose project: both use the same named database volume and loopback ports.

## Build identity and profiles

Commit source changes, then run `make up`. The runtime command injects the Git
commit and service version into all three backend processes, their profiles, and
the frontend build. A tagged commit uses its tag as the version. Otherwise the
version is the first twelve characters of the commit SHA.

`python3 tools/runtime.py up --allow-dirty` is available for development. Such a
build is marked `dirty` and has no source-commit label, so it cannot masquerade as
the clean GitHub source. Normal comparison runs require a clean checkout.

Python collects CPU and sampled memory profiles with `pyroscope-io` 1.2.3. Go
collects CPU, allocation and live-heap profiles with `pyroscope-go`. Both send
profiles to Alloy on the private Compose network. Go also correlates trace spans
with profiles. Process-wide Python profiling does not imply exact Python
request-to-profile correlation.

Profiles carry `service_name`, `service_version`, `service_repository`,
`service_git_ref` and `service_root_path`. The native Pyroscope GitHub source
integration may ask each viewer to connect their GitHub account. The data source
PAT is separate from this per-viewer source-code authorization.

## Repeatable workload

```sh
make up
python3 tools/load.py
# Optional, explicitly recorded overrides:
RATE=20 DURATION=2m python3 tools/load.py
```

The default is 10 order-list requests per second for two minutes, five warm VUs,
and at most ten VUs. It creates a dedicated UUID fixture run, maintains customer
cookies, and exercises browser-facing Python -> Go -> PostgreSQL. It makes no
LLM calls and creates no replacement orders. Thresholds require less than 1%
HTTP failures, more than 99% successful checks and no dropped iterations.
Exact UTC windows, version and results go to ignored `runs/foundation/load-*.json`.
Use equal rates, durations and container resources for version comparisons.

To restore a reviewed version, check out its tag in this checkout and run
`make up`. This changes application containers; it preserves the database volume.
Existing demo scenarios have their own reset controls. The workload does not
activate a fault or reset the presenter's current customer run.

## Native dashboards

- `/d/pd-runtime-versions`: CPU, allocations and live heap by service version;
  customer request throughput and p95 latency; selected-version CPU flamegraph.
- `/d/pd-ai-delivery`: native model-cost counters, actual merged PRs and median
  creation-to-merge time, CI workflow outcomes, published GitHub releases.

Generate with `python3 infra/grafana/foundation_dashboards.py`. Validate and push
only `infra/grafana/foundation/resources` through gcx in `demotests_gcloud`.
The dashboards live in the existing `parceldesk-demo` folder. Never replace a
missing result with fabricated history. Model-cost counter increases need two
samples, exclude subscriptions, and currently cover coding agents in this demo
stack. They are not an exact cost attribution to a GitHub PR or release.

GitHub PR time is `merged_at - created_at`, including drafts and review wait.
Releases are publications, not confirmed production deployments. GitHub's plugin
caches responses, so allow up to five minutes for a new merge or release to appear.
These measures describe delivery and consumption; causal productivity gains need
a comparison design and more history.

## GitHub data source

Use a repository-restricted fine-grained PAT in `.secrets/github_read_token`
(mode 0600), with Contents, Pull requests and Actions read permissions. The native
plugin is `grafana-github-datasource`; the datasource UID is `pd-github`.
`infra/grafana/foundation/github.datasource.json` references the local secret
file and never contains its value. Test with:

```sh
gcx --context demotests_gcloud datasources health pd-github -o json
```

The initial stack exposed a service-account parsing error on the new datasource
create API. Creation used gcx's legacy `/api/datasources` endpoint after the typed
command failed. Reads and health checks use the dedicated commands normally.

## Coding-agent access

Install the official `agento11y` launcher into ignored `tools/bin/`. This setup
uses v0.48.0. Credentials live under `.secrets/coding-config/`. Start CLI agents
through `tools/coding/launch.sh claude` or `tools/coding/launch.sh codex`.
Cursor uses project-scoped `.cursor/hooks.json`; open this checkout in Cursor.
After the first Codex launcher start, trust the agento11y hooks in `/hooks`.
The launcher records metadata only and adds repository, branch, project and team
tags. It does not import unrelated historical sessions or calculate task success.

`tools/coding/launch.sh doctor --json` checks the generation, metrics and traces
export pipelines. A successful doctor probe establishes connectivity; observing
a real session establishes that its host integration ran.

All editors receive the same query instructions through `AGENTS.md`, `CLAUDE.md`
and the Cursor rule. Use the existing host gcx context; never copy its credentials
into editor instructions, a prompt, or the repository.

```sh
gcx --context demotests_gcloud profiles labels -d grafanacloud-profiles -l service_version --since 1h -o json
gcx --context demotests_gcloud profiles query -d grafanacloud-profiles \
  '{service_name="parceldesk-agent"}' \
  --profile-type process_cpu:cpu:nanoseconds:cpu:nanoseconds --since 15m -o json
```

The recurring feature change, fault and customer-facing narrative are the next
design step. This foundation does not reuse the legacy local accepted-candidate
ledger as evidence of native productivity measurement.
