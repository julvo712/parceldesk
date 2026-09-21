# Project observer

This dedicated container polls Docker Engine API v1.45 using only GET requests to the fixed list/stats/logs endpoints. It filters and independently checks `com.docker.compose.project=parceldesk` and the known service allowlist. No API proxy or mutation method is exposed. Only this container receives the Docker socket; `:ro` on a Unix socket does not itself enforce Engine API authorization.

`GET :9108/metrics` exposes Engine-derived CPU seconds, throttled seconds/periods, memory usage/working-set/limit and network bytes. Labels are bounded service/project/replica values. Missing source fields stay absent. The working set is usage minus inactive file cache, not RSS. `rate(parceldesk_container_cpu_usage_seconds_total[1m])` is CPU cores consumed. Throttled-period ratio compares cumulative throttled periods to cumulative scheduling periods; it is not a percentage of request latency.

`GET :9108/health` requires a successful collection within 30 seconds. Collection runs every five seconds; Alloy scrapes every ten. The observer reports its collection errors, last-success time and forwarded-log count.

Only operations/carrier stdout is shipped to Alloy's internal Loki push receiver. Docker frame timestamps preserve nanoseconds. Cursors advance only after accepted push; overlapping polls deduplicate by timestamp/content signature and state persists in `observer-data`. Python logs already use direct OTLP and are excluded. The initial poll covers the previous minute and is capped at 5,000 lines per container; this bounded demo collector is not a general archival log agent.

## Verify

```sh
python3 -m unittest discover -s tools/observer -p 'test_*.py'
gcx --context demotests_gcloud metrics query -d grafanacloud-prom 'count(parceldesk_container_cpu_usage_seconds_total)' -o json
gcx --context demotests_gcloud logs query -d grafanacloud-logs '{service_name="parceldesk-operations",source="docker-stdout"}' --limit 3 -o json
```

Initial live verification returned seven container CPU/throttling series, `pg_up=1` for `parceldesk-postgres`, and real operations stdout entries in Cloud. The PostgreSQL role is provisioned by `provision-monitor.sql` using the database container's existing environment; no password is printed.
