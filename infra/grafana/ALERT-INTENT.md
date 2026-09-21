# Optional sample-aware alert intent

These rules are intentionally **not installed** during dashboard provisioning. Dashboard creation must not unexpectedly modify alerting or send notifications.

## API latency

Enable once the actual API duration histogram is measured, the desired threshold is agreed, and the probe/runtime cohort can be scoped. Require at least 20 real requests in the window; an empty histogram is NoData, not healthy. A short demo window is not a 28-day SLO.

## Quality regression

Scope to the executed suite and prompt version, require the suite's minimum completed-case count, and alert only on its deterministic primary verdict. Checks-per-case and native judge events are different denominators. Pending, timeout and evaluator error are separate states. Do not mix background experiment events into customer availability.

## Guard service unavailable

The fail-closed behavior must be visible independently of a successful policy denial. An outage should not inflate attack-prevention success. Configure NoData explicitly and retain source=local/native distinctions.

## Delivery

When optionally enabled, use dedicated gcx alert commands, dry-run where supported, independent readback and a ParcelDesk-owned rule group. Display alert state only. No outbound contact point or routing change is part of this demo setup.
