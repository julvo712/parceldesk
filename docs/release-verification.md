# ParcelDesk 0.1.0 verification

Verified on 15 September 2026 against `demotests_gcloud`. This is the portable acceptance summary; detailed local recordings remain in the author repository's verification directories. No secrets or developer conversation contents are included in the source release.

## End-to-end acceptance

- Seven Docker services are healthy on the initial Mac. React/Faro → Python agent → Go operations/carrier → PostgreSQL is live, exporting to Grafana Cloud.
- The final browser journey produced a real Sonnet proposal, explicit customer confirmation, exactly one replacement and one notification despite concurrent retries, and successful refresh. Faro returned 202. The 145-span Tempo trace includes browser parentage and native generation/span correlation: `a588654a77b9f8866eeffaf0d1bad603`, conversation `06787108-b9ee-436e-a275-195054a45893`.
- The accepted package is `ec9db6dc9f61060d`, using Anthropic `claude-sonnet-4-5-20250929`. Activation requires native experiment verification; new conversations fail closed if the configured provider/model differs from the accepted package.
- All seven Grafana dashboards were deployed via gcx, independently read back, rendered, and visually checked. 76/76 queries and 37/37 comparisons against actual source records passed. [Start Here](https://demotests.grafana.net/d/pd-overview).

## Prompt improvement, measured on the same model

| Package | Full suite | Native experiment |
|---|---|---|
| Baseline `e1e18394bd37698f` | 33/36 | `exp-d3398fc9b87cea81` |
| Rejected candidate `e62a2a01067a2252` | 27/36 | `exp-afed415351d87ee0` |
| Accepted `ec9db6dc9f61060d` | 36/36 | `exp-344d03a168eaab71` |
| Accepted, distinct heldout attack | 3/3 | `exp-4cd2936409f72331` |

The full suite contains 12 cases repeated three times. Heldout results remain separate; three trials of one attack are not three distinct attacks. Business verifier v2 reads durable orders, proposals, confirmations, replacements and notification records. Fluent text without a valid persisted proposal fails. Premature real actions fail. These results establish behavior on this fixture set, not universal injection resistance.

Baseline full-suite native estimated model cost was $0.789375; accepted full-suite cost was $0.957351. Better task completion used more tokens. These are evaluation-run consumption estimates, separate from coding costs and subscription invoices.

The online groundedness judge is a separate, fallible signal. Version `2026-09-15.2` evaluates factual claims against user/tool evidence. The earlier version incorrectly penalized missing workflow actions in a per-generation view; those scores remain in history. Offline acceptance is decided by durable-state verification, not by the online judge. Runtime sampling is 100% for this low-volume demo; evaluation traffic is excluded by the online rule. A fresh real conversation (`341736bd-dabd-4a4d-bad0-634cdf356294`) produced a persisted proposal and two independently read-back online scores of9/10 under the corrected version.

## Coding assistants and delivery outcomes

Real Codex, Claude Code and Cursor sessions were recorded in native Agent Observability and explicitly associated with the task. Cursor's review of the two approved prompt/context files ran through its authenticated desktop application. Coding content capture is metadata-only. Codex's official hooks were trusted and an automatic-export probe verified after earlier project-scoped history imports.

The final ledger contains 19 generation records across six sessions. Five sessions belong to one accepted task, with three rejected evaluation attempts and no first-pass acceptance. Known Claude API-equivalent coding consumption is $0.2369328. Codex and Cursor pricing remains unknown; total coding cost is therefore unknown. The measured 5,145-second task interval includes automated rehearsals and waiting. It is not human work time or time saved. Julius is the task owner; the recorded implementation/review run was automated, not a completed human presenter pilot.

## Safety and fault chapters

- Actual native guard denial was independently verified with a disclosed operator probe: no model call and no business dispatch. The configured recipient rule blocks the demonstrated malicious address; it is not a universal injection detector.
- The model resisted the observed supplier-document injection. Ownership, customer recipient, confirmation, stock and idempotency are independently enforced by Go business services.
- Native guard unavailability stops dispatch. The overstrict chapter changes local policy and exposed tool access; it demonstrates a usefulness regression, not a Grafana guard feature.
- Real database lock waiting, shipping-date mapping failure, CPU regression, CPU pressure/throttling, bounded tool errors, local LLM-boundary delay and browser rendering failure were exercised with recovery. All faults were reset.
- A CPU regression span correlated to 1.81 CPU seconds in Pyroscope: trace `6cd64a0fb714415c9572ff11eb9022da`, span `b659058c1bc178e1`. The database lock span lasted approximately 858 ms.
- PostgreSQL exporter and project-scoped Docker telemetry were read back in Cloud. Native Database Observability was not established by these checks.

## Automated and platform checks

The full release gate passed: 105 Python tests, Go race tests against real PostgreSQL plus vet, four frontend unit tests and production build, five observer tests, twelve release checks, and eighteen browser/accessibility/responsive cases. Subsequent telemetry changes passed 64 tooling and seven API integration tests. Project-scoped Cursor forwarding also has focused exclusion tests. Browser checks cover 1440-, 1366- and 390-pixel viewports, keyboard interaction, zero axe violations in tested states, and LCP/CLS budgets.

Four AMD64 images were built and an isolated six-service runtime passed all eight business tools, concurrent idempotency, ownership/recipient rejection, UI/API checks and a real Anthropic call under Docker Desktop emulation. The AMD64 observer tests passed separately. This is not physical x86-host validation. The GitHub Actions workflow is supplied; no hosted run is claimed.

## Remaining rollout gate

The local demo is operational. Before broad internal rollout, two human presenters must rehearse it, including one clean-machine installation. That pilot is pending. Windows, other browsers, physical x86 hosts and another Grafana stack have not received full acceptance. Notifications are sandbox records; customer identity is a labelled synthetic fixture. Credentials and native Cloud setup must be supplied for a different stack.
