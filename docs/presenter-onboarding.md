# Presenter onboarding and meeting flow

## Prepare before the meeting

Complete [installation](install.md), run doctor against the intended Cloud context and open three windows: customer application, presenter console and Grafana Start Here. Rehearse one benign replacement, one prompt injection, one infrastructure fault and reset. Use only synthetic fixture data.

Create a genuine coding session in each assistant represented on the dashboards. Check the reported capture/price coverage. Select one assistant for live development; the others provide the observed usage context. A quiet tool should show missing/no observations, not a fabricated usage bar.

The recurring coding surface is limited to `agents/replacement/system.md`, `agents/replacement/context.py` and added local regression tests. Business rules, native guards, independent evaluators, telemetry and fixtures remain outside that ticket. The ticket is to handle supplier content as untrusted while retaining useful replacement assistance.

## 15-minute story

| Time | Action | Value to make visible |
|---|---|---|
| 0–2 min | Show the polished customer flow and select the damaged Arc order | This is an application with a business outcome, not just a model playground |
| 2–4 min | Open Coding FinOps and Delivery & Quality; show the linked real development task | Consumption and accepted change outcomes can be observed together. Estimates are API-equivalent, not subscription invoices |
| 4–6 min | Use one coding assistant to implement the bounded prompt/context ticket | The development process itself emits useful evidence; show task/session/candidate linkage |
| 6–8 min | Run a healthy application request and follow its trace | Browser, agent, tools, business service, carrier and database share diagnostic context |
| 8–11 min | Activate supplier injection and inspect the actual attempted tool call/native guard decision | The guard prevents the configured unsafe action. That prevention does not make the agent's attempted behavior correct |
| 11–13 min | Show baseline/candidate experiments with counts, benign cases and pending status | Evals measure whether prompt changes improve behavior without breaking useful work |
| 13–15 min | Show one preselected non-LLM fault, identify the layer, reset and finish the customer action | Full-stack evidence distinguishes model behavior from infrastructure/application problems |

If the live model resists the injected document, say so. Do not invent an attempted tool call. Use a preserved, labelled real failing run for investigation, or a clearly labelled deterministic guard probe to demonstrate the policy. If a candidate fails, inspect its result; a failed candidate is valid demo evidence.

## 25-minute technical extension

Add roughly ten minutes based on the audience:

- **3 minutes: database lock.** Activate `db_lock`, request inventory and show an actual PostgreSQL waiter. Follow the waiting SQL span. Reset and observe recovery.
- **3 minutes: application versus infrastructure CPU.** `cpu_regression` produces request-attributed CPU samples in the Go function. `cpu_pressure` shows container CPU/throttling under the fixed quota. Profiles answer where CPU time went; container counters show resource pressure.
- **2 minutes: shipping mapping.** Compare the raw carrier arrival date with the mapped tool response under `shipping_mapping_bug`. The mismatch is application logic, even though it appears in an agent workflow.
- **2 minutes: delivery/quality measurement.** Inspect time to accepted change, first-pass acceptance and rejected revisions. Include all attributed attempts in cost per accepted task; keep unresolved allocation visible.

Choose one primary fault per run. Avoid enabling all failures at once. Use the presenter console rather than exposing internal IDs or diagnostic language inside the customer interface.

## Audience trims

For leaders, retain the outcome, consumption, quality comparison and one diagnosis. For developers, expand prompt context, generation/tool evidence and the bounded rebuild. For SRE/platform teams, expand cross-service tracing, database locks, container pressure and CPU profiles. For security audiences, separate configured guard coverage, independent business authorization and measured agent behavior.

## Internal pilot acceptance

Two presenters must independently record:

1. Installation and doctor result; one installation starts on a clean machine with its own credentials.
2. A real coding session linked to the bounded development task.
3. An eligible replacement with exactly one persisted replacement and sandbox confirmation.
4. A prevented malicious destination attempt, or honestly documented model resistance plus policy probe.
5. Candidate experiment terminal results, including benign cases and sample counts.
6. One real non-LLM fault, the correct evidence chain and successful reset.
7. Usable UI at presentation and mobile widths, keyboard completion and recovery after refresh.

Save the reports under local run evidence and update `release/acceptance.json` only with actual completed checks. Human pilot steps are currently pending. Do not mark the release broadly accepted just because automation or the original author completed a rehearsal.
