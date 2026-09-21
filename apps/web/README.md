# ParcelDesk web

React 19 + TypeScript + Vite 7. Customer experience at `/`; presenter console at `/presenter` or the default presenter origin on port 3101. Images are local generated assets in `public/images`.

## Build and verify

```sh
npm ci
npm run build
npm test
npx playwright install chromium
npm run test:browser
```

On the development Mac, an installed Chrome can be selected with `PLAYWRIGHT_CHROMIUM_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'`. Browser tests require an environment that permits browser process creation. They use HTTP fixtures and disable Faro explicitly; fixture runs never claim real model or telemetry evidence.

`npm run test:browser` covers three viewport sizes: 1440×900, 1366×768 and 390×844. Checks include explicit confirmation, refresh persistence, failed-confirmation recovery, offline input handling, axe accessibility, keyboard focus and local LCP/CLS budgets. Screenshots and performance attachments are written to the Playwright report. These are local browser measurements, not a production Faro or real-provider acceptance claim.

For the actual Docker deployment, run:

```sh
PLAYWRIGHT_CHROMIUM_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' node tests/live-smoke.mjs
```

The live script creates a real isolated demo run, uses the configured actual provider, confirms the replacement, refreshes the page and writes screenshots, W3C request headers, collector HTTP responses and server evidence under `verification/live`. It exits nonzero if the journey fails. Collector HTTP acceptance is not proof of downstream query visibility; query Grafana separately.

## Deployment

The Dockerfile expects **build context `apps/web`**, uses Node 24 for compilation and serves the static build with nginx on port 8080. Compose mounts the authoritative dual-origin nginx config. Its customer origin must not expose `/control`. The default standalone nginx config proxies API traffic to `agent-api:8000`, collects at the same-origin `/collect`, and disables buffering for streamed turns.

Build-time options: `VITE_GRAFANA_URL` (default `https://demotests.grafana.net`), `VITE_APP_ORIGIN` (default host port3100), `VITE_FARO_ENABLED=false` only for explicitly isolated browser fixtures. No credential belongs in any `VITE_*` value.

## API contract

- `POST /api/demo-session`: `{customer_id:'C1',run_id?}`; opaque HttpOnly session cookie.
- `GET /api/orders`: `{orders:[{order_id,product_name,delivered_at,status?,sku?}]}`.
- `POST /api/conversations`: `{order_id}`; returns `conversation_id`.
- `GET /api/conversations/{id}`: messages `{role,content}`, proposal, status and active scenario. Refresh is authoritative.
- `POST /api/conversations/{id}/turns`: `{message,request_id}`; fetch-readable SSE. Events support `status`, `text_delta`, `proposal`, `blocked`, `completed`, `error`. `blocked` and `completed` are terminal. Every event identity is deduplicated.
- `POST /api/proposals/{id}/confirm`: `{idempotency_key}`. The same key persists per proposal; synchronous UI locking prevents duplicate clicks. Confirmation is shown only after authoritative conversation recovery says confirmed.
- Proposal fields: `proposal_id`, `arrival_date`, `product_name?`, `shipping_method?`, `status?`, `deadline_met?`, `summary?`, `replacement_id?`.
- Presenter uses `/control/status`, `POST /control/runs`, `POST`/`DELETE /control/runs/{id}/scenario`, `GET /control/runs/{id}/evidence`.

No model content enters general browser telemetry metadata. Console capture is off. The Faro tracing SDK loads separately; propagation is restricted to application APIs and excludes the collector and presenter controls. Browser errors remain independently observable through the resolution boundary. Native-cloud query verification is owned by the deployment acceptance workflow.
