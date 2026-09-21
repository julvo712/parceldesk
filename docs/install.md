# Install ParcelDesk

ParcelDesk runs on local Docker and exports real application, coding-agent and infrastructure telemetry to a deliberately selected Grafana Cloud stack. Customer UI: **http://localhost:3100**. Presenter console: **http://localhost:3101**. These ports bind to loopback.

## Requirements

- Docker Engine with Compose v2+, running Linux containers. Initial verified host: Docker 29.4.0 on macOS Apple Silicon. Allocate at least 4 CPU cores, 6 GiB RAM and 10 GiB disk; the operations service deliberately has a one-CPU quota for the CPU-pressure chapter.
- Python 3.12+ for release scripts and a working `gcx` installation.
- A Grafana Cloud context you explicitly select, with dashboard/folder read/write and datasource/query permissions. The supplied deployment uses `demotests_gcloud`.
- Separate target-stack ingestion credentials for OTLP/metrics/logs/Agent Observability and profiles, plus a real supported LLM provider key. A Grafana service-account administration token is not automatically a Cloud Access Policy ingestion token.
- Native Agent Observability hooks, evaluator and frontend application configured in the selected stack. A successful Docker start does not establish these product permissions.

## Unpack and verify

```sh
shasum -a 256 -c parceldesk-0.1.0.tar.gz.sha256
tar -xzf parceldesk-0.1.0.tar.gz
cd parceldesk-0.1.0
```

The archive contains source, dependency lockfiles, generated visual assets and manifests. It contains no credentials, installed host coding agents, `node_modules`, virtual environments, local Docker data or previous runs. BuildKit downloads the pinned dependencies on installation; network access is required. Optional OCI image archives are built separately with `release/build.py --images`.

## Select the Cloud target

Authenticate `gcx` against your intended stack using its supported login flow. Always specify the context explicitly. Copy `release/cloud-config.example.json` to a local file and set its context, target endpoints, tenant IDs and Faro collector URL using the stack's connection setup. The example contains the nonsecret original `demotests_gcloud` endpoints only.

The installer discovers datasource UIDs through `gcx`. If a stack has multiple datasources of one kind, set `datasources.prometheus`, `.loki`, `.tempo`, `.pyroscope` to the selected UIDs in the profile. It creates a separate local Alloy/Compose override and dashboard output, preserving the shipped definitions.

Place these files in `.secrets/` with directory mode 0700 and file mode 0600:

| File | Purpose |
|---|---|
| `cloud_token` | Target-stack ingestion and Agent Observability credential |
| `profiles_token` | Profiles ingestion credential |
| `gemini_key` | Gemini provider credential, if used |
| `anthropic_key` | Anthropic provider credential; required by the default profile |
| `openai_key` | OpenAI provider credential, only when explicitly selected |

The default selected provider is **Anthropic**, model **claude-sonnet-4-5-20250929**, and its funded key must be present. Set `llm_provider` and `llm_model` in the nonsecret profile to deliberately select another supported provider. Installation never switches providers automatically because another key exists. The installer creates missing local database/service/session secrets with cryptographically random values. `PARCELDESK_CLOUD_TOKEN`, `PARCELDESK_PROFILES_TOKEN`, `GEMINI_API_KEY` , `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` may supply missing files through your process environment. Never paste secrets into a release profile, dashboard, source file or shell history.

## Install and verify

```sh
python3 release/manage.py install --context demotests_gcloud --cloud-config release/cloud-config.example.json
python3 release/manage.py doctor --context demotests_gcloud
```

Installation builds/starts the project, provisions a PostgreSQL monitoring role with no business-table write privileges, and deploys the seven owned dashboards through gcx with validation, dry-run and independent readback. The readiness check includes local services and recent container/PostgreSQL/application metrics in Cloud. It reports missing observations explicitly.

`doctor --local-only` is useful while offline but does not establish Cloud delivery. Model generations, guard enforcement, native evaluations, browser traces and CPU-profile correlation require the separate real demo acceptance journey. Configure the coding integrations on each presenter's host and verify a real session from every assistant used in the meeting.

Before distributing beyond the initial author, complete the pilot in [presenter onboarding](presenter-onboarding.md). See [support matrix](support-matrix.md) for the difference between build targets and verified runtime coverage.

## Release baseline and healthy first launch

A source archive excludes `.git`. The installer scans the release for credentials, initializes a repository inside the extracted ParcelDesk directory, commits only the scanned source allowlist, and creates `parceldesk-baseline`. A surrounding parent repository is never used. An existing repository is never automatically committed: its canonical baseline tag must exist, or the installer can copy the existing `demo-baseline` tag. Otherwise tag the reviewed baseline explicitly before installation.

On first install, `agents/reference/validated/manifest.json` binds the shipped healthy reference to its exact prompt/context hash, provider, model and recorded native experiment. The installer checks those fields, copies immutable bytes into the local `runs/packages` directory and writes an activation manifest marked `shipped_reference`. It preserves any existing activation. It does not invent a coding task or accepted-candidate ledger event. The weaker `agents/replacement` package remains the recurring coding surface. A different model needs its own validated reference before this first-launch path can activate it.
