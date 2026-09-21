# ParcelDesk dashboards

Seven native Grafana v2 dashboards, generated and managed through gcx in the **ParcelDesk Demo** folder.

[Open Start Here](https://demotests.grafana.net/d/pd-overview) · [Coding FinOps](https://demotests.grafana.net/d/pd-coding-finops) · [Adoption](https://demotests.grafana.net/d/pd-coding-adoption) · [Delivery](https://demotests.grafana.net/d/pd-delivery-quality) · [Agent Quality](https://demotests.grafana.net/d/pd-agent-quality) · [Runtime](https://demotests.grafana.net/d/pd-runtime) · [Readiness](https://demotests.grafana.net/d/pd-demo-readiness)

From the `parceldesk` directory:

```bash
python3 infra/grafana/generate.py
python3 infra/grafana/manage.py deploy --context demotests_gcloud
python3 infra/grafana/manage.py verify --context demotests_gcloud
python3 infra/grafana/manage.py queries --context demotests_gcloud
python3 infra/grafana/manage.py snapshot --context demotests_gcloud
python3 infra/grafana/verify_values.py --context demotests_gcloud --expected /path/to/authentic-ledger-expectations.json
```

`deploy` rejects unowned resource IDs and existing resources missing the project ownership label. It saves previous owned manifests under `backups/`, validates, insists on an eight-resource successful dry run, pushes the folder first, and independently compares every complete dashboard spec and folder annotation. It never modifies datasource configuration or unrelated resources.

Rollback an explicitly selected complete backup:

```bash
python3 infra/grafana/manage.py rollback --context demotests_gcloud --backup infra/grafana/backups/TIMESTAMP
```

The rollback path must contain exactly the seven owned dashboards and owned folder. First-deployment partial backups are not complete rollback sets. Backups are local resource specs, without credentials. Keep a known-good backup with release artifacts.

Datasource defaults can be overridden at generation using `--prometheus`, `--loki`, `--tempo`, `--pyroscope`. For another stack explicitly select its context on every manage operation. Dashboard links are relative to that stack; initial links in `manifest.json` identify the original installation.

## Evidence

- `evidence/deployment.json`: last deployment, dry-run result, previous backup.
- `evidence/parity.json`: independently reread spec SHA-256 values and folder check.
- `evidence/queries.json`: every expanded query, result count and sample evidence.
- `evidence/snapshots/`: real server-rendered Grafana PNGs, never generated marketing images.
- `evidence/values.json`: source-ledger comparison when authentic expectations are supplied.

See [MEASUREMENT-CONTRACT.md](MEASUREMENT-CONTRACT.md) for labels, denominators, time semantics, scope and unknown values. See [ALERT-INTENT.md](ALERT-INTENT.md) for optional alert rules. Source/visual acceptance is separate from the mere presence of dashboard JSON.

## Management checks

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s infra/grafana -p test_management.py -v
PYTHONDONTWRITEBYTECODE=1 python3 infra/grafana/test_rollback_live.py --context demotests_gcloud
```

The live rollback test creates only seven `pd-validation-*` resources inside `parceldesk-validation`, refuses existing-name collisions, validates each revision, independently compares the install/upgrade/rollback specs, then cleans those individually named owned resources. Its report is `evidence/rollback-validation.json`.

The expected-value input requires `source_evidence` (an authentic ledger checksum/run reference), `synthetic: false`, optional `datasource`, and a nonempty `checks` array. Each check supplies `name`, a concrete scalar PromQL `query`, its source-derived numerical `expected`, and optional absolute/relative tolerances. The tool never creates expected values from the Cloud response itself.
