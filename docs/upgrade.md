# Upgrade and rollback

Run commands from the existing project root. Upgrades affect only the `parceldesk` Compose project. Credentials and mutable data stay local.

## Upgrade

1. Download the new approved archive and checksum. Verify the checksum independently.
2. End the active presentation and reset its fault lease.
3. Run:

```sh
python3 release/manage.py upgrade --archive /path/to/parceldesk-NEXT.tar.gz --context demotests_gcloud
python3 release/manage.py doctor --context demotests_gcloud
```

The command verifies archive member hashes and paths, saves a source archive, PostgreSQL dump and exact current local image IDs under `runs/releases/<timestamp>/`, then replaces release-owned source and rebuilds the project. It does not replace secrets. Keep that snapshot until the real replacement, blocked injection, evaluation and reset checks pass. Apply/verify updated dashboards through the selected context as described in `infra/grafana/README.md`; dashboard management retains its own resource backups.

An image build or readiness failure is a failed upgrade. Do not describe it as deployed successfully. Use the recorded snapshot to recover.

## Rollback

```sh
python3 release/manage.py rollback --snapshot runs/releases/TIMESTAMP --context demotests_gcloud
```

Rollback verifies the snapshot, restores source and uses the exact retained local image IDs. Do not prune those images before the release has been accepted. If images are missing, rollback stops instead of quietly rebuilding different content.

If the migration set changed, rollback requires the explicit `--restore-database` flag. This restores the snapshot database and discards demo writes made after the snapshot:

```sh
python3 release/manage.py rollback --snapshot runs/releases/TIMESTAMP --restore-database --context demotests_gcloud
```

After restoration, run doctor and a fresh business journey. Resetting a fault lease and restoring a database are different operations. The database snapshot contains synthetic conversations, experiments and action ledgers; protect it as local application data even though it contains no real customer records.

## Remove the local deployment

```sh
python3 release/manage.py uninstall --owned-only
```

This stops/removes only project containers and its network. It preserves volumes, source, secrets, snapshots and Grafana Cloud resources. Add `--remove-data` only when you intentionally want this project's named volumes deleted. No command uses global Docker prune, removes other projects or deletes Cloud resources by broad title matching.
