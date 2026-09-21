# Grafana presenter dashboard

Open **[ParcelDesk | Presenter](https://demotests.grafana.net/d/pd-presenter)** on the Mac running the demo. The existing [local console](http://localhost:3101) remains available. Both operate the same selected run.

1. Click **Run** beside **Create demo run** and confirm.
2. Open the customer experience from the dashboard. The local link resolves the current run at click time and opens the customer app with that run ID, including when an older customer session exists.
3. Activate one of the ten scenario rows. The controller rejects overlapping faults; every fault expires within five minutes.
4. Follow the linked Grafana investigation views. Start a fresh customer conversation after changing scenario.
5. Click **Reset & verify**. The action succeeds only after the controller reads the run back as healthy. Customer actions and evidence are preserved.

The guard probe calls the real Grafana rule. It is an operator check, with no model generation and no possible business action. Its result and age are shown separately.

## Connection and freshness

Native Grafana table actions send POST requests from the browser to `http://localhost:3101/control/presenter/command`. If the browser asks for local-network access for the Grafana site, allow it to use these local controls. This deployment is for one presenter on the demo Mac. A colleague's browser on another machine addresses their own localhost.

Controller observations are scraped every ten seconds and exported to Grafana Cloud. Allow approximately 10–30 seconds for panels to reflect an action. Readback age becomes amber at 30 seconds and red at 60 seconds. A Grafana success toast is an API receipt; verify the current scenario and fresh state. Existing data can remain visible when the Mac is offline, so freshness is essential.

The Cloud stack does not advertise `vizActionsAuth`. This version therefore uses generally available direct browser actions, not preview authenticated Infinity actions or a public tunnel. Infinity is used only to render a static command catalog; those rows are explicitly not telemetry. Authenticated Infinity actions plus PDC are a future alternative, requiring separate activation and end-to-end validation.

## Scope and controls

- Only the configured Grafana origin can call the bridge. `GRAFANA_URL` supplies the default; `PRESENTER_GRAFANA_ORIGIN` can override it.
- Only JSON POST, the native `X-Grafana-Action: 1` marker and an allowlisted command are accepted. Preflight grants apply only to this endpoint. Existing customer/controller endpoints keep their original origin restrictions.
- No secret, admin token, arbitrary URL, script or shell command is embedded in the dashboard. The controller stays bound to loopback through Docker.
- Creating a run during an active fault is rejected. Duplicate run creation within five seconds is rejected. Reset is repeatable, and failures remain visible in action receipts.
- This is a browser-local control boundary, not a replacement for authenticated multi-user administration. Do not expose port 3101 on a public interface.
- Commands and verification outcomes are emitted as `presenter_action` logs. New metrics use `parceldesk_presenter_*`. Only the current run is exported by the presenter collector; historical logs preserve prior actions.

## Maintenance

Dashboard source: `infra/grafana/presenter_dashboard.py`, integrated into the existing generator and gcx deployment/verification commands. Resource UID: `pd-presenter`; folder: `parceldesk-demo`.

Controller tests: `apps/agent/tests/test_presenter.py`. Browser integration: `apps/web/tests/grafana-presenter.mjs`. Detailed evidence lives under `infra/grafana/evidence/presenter/` in the author repository.

## Verification recorded on 16 September 2026

The dashboard was deployed through gcx, independently read back and visually inspected with the Grafana renderer. All 90 Prometheus/LogQL queries across the eight dashboards passed. All ten scenario activation/reset pairs and the actual native guard denial passed through the controller endpoint. The existing API suite passes 43 tests, including seven focused presenter tests; twelve release tests pass. The original local console remains served on port 3101.

After explicit user approval, the isolated Chrome test passed with the normal local-network site permission. Real dashboard buttons created a run, activated supplier injection, reset it, performed the native guard check and refreshed evidence. Fresh run, fault and healthy recovery states were independently queried in Grafana Cloud. The customer link selected the correct run; the guard denied the probe with no model call or business action. No local action requests failed. The test reset the fault and closed the temporary browser context. Cloud HTML/read/query requests used the existing gcx authorization; local action requests traveled directly from the real Grafana UI to localhost. No Grafana folder permissions or permanent browser settings changed.
