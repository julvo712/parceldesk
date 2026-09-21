# Optional failure chapters

All controls are local to ParcelDesk and expire within five minutes. Use one fault at a time in a fresh run. Reset in the presenter, then make a new request. A reset click alone is not proof of recovery.

| Failure | What the audience sees | Evidence that identifies the layer | Recovery |
|---|---|---|---|
| Supplier injection | Supplier text attempts to redirect customer data | Actual generation and proposed tool call; native guard decision if attempted. If resisted, show resistance plus the separately labeled operator guard check. | Clear lease; legitimate replacement still works. |
| Guard unavailable | Safe action cannot proceed while the synchronous decision path is unavailable | `guard_unavailable`, no dispatched business tool, no replacement/notification | Clear lease; real allowed guard round trip and successful proposal. |
| Overstrict agent configuration | Useful requests are refused | A real generation under an intentionally restrictive local policy with no exposed tools; benign eval completion fails. This is not a Grafana guard verdict. | Restore policy/tool availability; fresh request succeeds. |
| LLM boundary delay | Customer waits longer | Artificial delay is explicitly placed at the application/provider boundary. Compare generation/provider timing with surrounding request time. Do not claim the vendor was slow. | Reset; repeat request and compare timing. |
| Tool retry loop | Repeated stock-read failures exhaust bounded workflow | Real tool errors and repeated attempts; six-generation/twelve-tool/90-second caps prevent an unbounded loop | Reset; inventory reads and proposal recover. |
| Database lock | Replacement workflow stalls on a stock read | Real PostgreSQL waiter/blocker and long SQL span; exporter health alone does not establish native Database Observability. | Release lock; query and request complete. |
| Shipping mapping bug | An apparently reasonable arrival promise is wrong | Raw carrier quote compared with the mapped application result; verifier rejects the mismatch. The LLM may faithfully repeat bad application data. | Reset mapping; raw and mapped dates agree. |
| CPU regression | Inventory tool is slow with healthy dependencies | Slow Go span linked to its exact sampled CPU profile and `cpuWork` frames | Reset; work and duration return to normal. |
| CPU pressure | Many operations slow under resource contention | Real container CPU and throttled periods, correlated with latency | Stop the bounded worker; usage/throttling rate and request latency recover. |
| Browser rendering error | Customer resolution component fails | Native Faro browser exception/session, while backend evidence can remain healthy | Reset fault; retry/reload restores the durable state. |

## Cloud outage or delayed evidence

The customer state lives in PostgreSQL. Ordinary telemetry export is asynchronous; missing Cloud visibility must be shown as missing/stale. The synchronous remote guard is intentionally fail-closed: an unavailable guard stops covered actions. Do not disable it to keep the demo moving.

Keep dated real trace/profile/evaluation evidence available as a fallback and explicitly label it saved. Native experiments may finish before their report becomes queryable; the host verifier waits for completed unique trial scores before activation. A pending report cannot be accepted.

## Proven CPU example

The build rehearsal recorded trace `6cd64a0fb714415c9572ff11eb9022da`, CPU span `b659058c1bc178e1`, 1.81 sampled CPU seconds, and a separate saturation run with 26 additional throttled periods. See [the actual fault report](verification/go-fault-rehearsal.md). These are saved real observations, not promises that a future run will have identical timings.
