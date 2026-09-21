# ParcelDesk: 25-minute presenter script

## The story

“I’m building a replacement assistant for an audio retailer. I want to know whether my coding assistants are helping me deliver a working change, and whether the resulting customer experience is reliable. Grafana connects the development evidence with the application’s production behavior.”

Use one coding assistant live. Codex, Claude Code and Cursor are alternative ways to perform the same bounded change. Their previous genuine sessions remain available for comparison. Do not spend the meeting installing integrations.

## Before the audience arrives

Run `make doctor`, open [ParcelDesk](http://localhost:3100), the [presenter console](http://localhost:3101), and [Start Here](https://demotests.grafana.net/d/pd-overview). Check the selected model, active prompt version, signal freshness and current fault. Use a fresh run and keep the presenter console on the operator screen. Leave all faults off initially.

Prepare a fresh worktree with `make demo-prepare RUN=meeting-001 TOOL=codex`. Open its two-file prompt package in your chosen assistant. Have the most recent completed baseline/candidate experiments open in separate tabs. If a new experiment is still running during the meeting, say so and use that saved real comparison; never label it live.

## Core sequence

| Time | Screen and action | Observation to establish | Value statement |
|---|---|---|---|
| 0–3 min | Customer app: sign in as Maya, choose PD-1042, ask “My headphones arrived damaged. Please arrange a replacement by 2026-09-20.” Review and confirm the proposal. | Real model/tool calls, accurate arrival, explicit confirmation and one persisted replacement. Refresh preserves it. | A useful customer outcome is the unit of success. Fluent text alone is insufficient. |
| 3–6 min | [Coding FinOps](https://demotests.grafana.net/d/pd-coding-finops), then [Delivery & Quality](https://demotests.grafana.net/d/pd-delivery-quality). Open a genuine session. | Tool/model token and cache usage, priced/unpriced coverage, explicit task links, submitted/rejected/accepted revisions. | Relate consumption to a verified delivery outcome. API-equivalent estimates are distinct from subscription bills. |
| 6–9 min | [Runtime](https://demotests.grafana.net/d/pd-runtime): drill from the request into its trace, generation, tools, logs and dependencies. | Browser → Python → Go → carrier/PostgreSQL with real IDs and timings. | A slow AI feature can be diagnosed across the entire request. |
| 9–12 min | Presenter: activate supplier injection. Start a fresh eligible customer conversation and ask it to read the handling guide. Open the actual generation and tool evidence. | Either the model resists, or it proposes a forbidden action that is blocked. Read the recorded result; do not promise a stochastic attack will succeed. | Model behavior and enforcement are separate evidence. |
| 12–14 min | In Maya’s confirmed replacement, use **Email your confirmation**. Enter `audit@external.invalid` and click **Send confirmation**. Show **Request blocked**, then the conversation’s native guard banner and its `guard_decision` log in Grafana. | The real customer action is denied before notification dispatch. The existing replacement remains confirmed; the verified-address policy is visible in the customer experience. | Julia can demonstrate the prohibited action and inspect the matching enforcement decision. |
| 14–18 min | Coding assistant in the isolated worktree: improve supplier trust boundaries, preserve dates, continue legitimate replacements and persist a proposal before requesting confirmation. Run `make demo-review`, `demo-submit`, then `demo-evaluate SUITE=full`, each with the same `RUN`. | Only system.md, context.py and newly added live tests can change. Hashes tie the exact candidate to the experiment. | The development workflow turns a model behavior defect into a reviewable change with evidence. |
| 18–22 min | Native Experiments: compare baseline and candidate on the same provider/model, suite and verifier version. Include no-stock, expired-order, benign suspicious wording and attack cases. | Primary verdict checks durable business state, raw carrier truth and absence of unconfirmed actions. Failed candidates remain visible. Separate online judge scores from deterministic trial verdicts. | Evals catch both unsafe behavior and “safe but useless” refusals or missing actions. Prompt wording is a hypothesis until tested. |
| 22–25 min | Activate only a fully accepted candidate using `make demo-activate RUN=...`. Start a new conversation; show successful replacement and refresh. Finish on the linked delivery record. | Existing conversations keep their pinned version. New ones use the accepted package. Exactly one replacement/notification persists. | Close the loop from coding consumption to evaluated change to customer outcome. |

## Pacing and credible claims

The full release experiment has 12 cases repeated three times. A meeting smoke run has three representative cases repeated twice. A smoke pass is useful live feedback, but it is not the full release gate. Allow the actual model/Cloud latency; never accelerate charts with fabricated events.

If coding or evaluation runs longer than four minutes, continue with the saved, dated real evidence and return to the new run at the end. If a candidate fails, show the failure and retain the last accepted version. This is a successful demonstration of the control, not a reason to bypass it.

Cost per accepted task includes all explicitly attributed attempts. Unknown model prices or cache semantics remain unknown. A review session is not an accepted code change; a commit is not a merged PR; elapsed time in this automated rehearsal is not measured human time saved.

Choose an optional chapter from [chapters.md](chapters.md) by replacing the development detail or extending the meeting. End every fault chapter with reset and a real recovery request.
