"""Run the actual guarded runtime against isolated trials and native Cloud experiments."""
import argparse
import asyncio
import json
import pathlib
import sys
import uuid
from contextlib import asynccontextmanager, aclosing

import anyio
import httpx
from opentelemetry import trace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'apps/agent/src'), str(ROOT / 'evals')]
from agento11y.experiments import Client as ExperimentClient, Experiment, TestSuite, TestCase, Candidate, Evaluator
from parceldesk import config, telemetry
from parceldesk.agent.runner import run_turn, snapshot_package
from parceldesk.guards.gateway import ToolGateway
from verifiers import verify


@asynccontextmanager
async def isolated_trial(request, ctx, order_id, scenario):
    """Keep the HTTP client alive until this trial's lease has been cleaned up."""
    rid = ctx['demo_run_id']
    # A cancelled create request may still have committed remotely. Reset is safe
    # for an absent run, so cleanup is attempted even if creation never returned.
    try:
        await request('POST', '/internal/runs', {
            'run_id': rid, 'customer_id': 'C1', 'business_date': '2026-09-15', 'scenario': 'healthy',
        })
        await request('POST', '/internal/conversations', {
            'run_id': rid, 'customer_id': 'C1', 'order_id': order_id,
            'conversation_id': ctx['conversation_id'], 'agent_version': ctx['agent_version'],
        })
        if scenario != 'healthy':
            await request('POST', f'/internal/runs/{rid}/scenario', {'scenario': scenario, 'ttl_seconds': 300})
        yield
    finally:
        with anyio.fail_after(45, shield=True):
            await request('DELETE', f'/internal/runs/{rid}/scenario')


async def shutdown_exporters(observer, providers):
    failures = []
    for exporter in [observer, *providers]:
        try:
            with anyio.fail_after(45, shield=True):
                await anyio.to_thread.run_sync(exporter.shutdown, abandon_on_cancel=True)
        except Exception as error:
            failures.append(error)
    if failures:
        raise ExceptionGroup('Telemetry shutdown failed', failures)


async def run_trials(jobs):
    # TaskGroup cancels and awaits siblings on failure, before HTTP/experiment exit.
    async with asyncio.TaskGroup() as group:
        for job in jobs:
            group.create_task(job)


async def run(args):
    case_rows = json.loads((ROOT / 'fixtures/cases.json').read_text())
    if args.suite == 'smoke':
        case_rows = [case_rows[i] for i in (0, 5, 9)]
    if args.suite == 'heldout':
        case_rows = json.loads((ROOT / 'fixtures/heldout.json').read_text())
    if not case_rows:
        raise ValueError('Evaluation suite must contain at least one case')
    trials = args.trials if args.trials is not None else (2 if args.suite == 'smoke' else 3)
    if trials < 1:
        raise ValueError('Trial count must be positive')
    max_calls = len(case_rows) * trials * 6
    if max_calls > args.max_calls:
        raise SystemExit(f'Budget refused: needs up to {max_calls} model calls; configured {args.max_calls}')

    frozen_path, version = snapshot_package(ROOT / 'runs/packages', args.candidate)
    suite = TestSuite('parceldesk-replacement', name='ParcelDesk replacement safety and quality', version='v1',
                     test_cases=[TestCase(c['id'], name=c['id'], category=c['category'], input=c,
                                          expected={'proposal': c['expect_proposal']}) for c in case_rows])
    report = {'agent_version': version, 'package_path': str(frozen_path), 'status': 'running', 'accepted': False,
              'completed_cases': 0, 'cases': [], 'model': config.MODEL, 'provider': config.PROVIDER,
              'max_model_calls': max_calls, 'max_output_tokens': max_calls * 2048, 'suite': args.suite,
              'evaluator_version': '2', 'suite_version': 'v1'}
    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    def save_report():
        temporary = out.with_suffix(out.suffix + '.tmp')
        temporary.write_text(json.dumps(report, default=str, indent=2))
        temporary.replace(out)

    sem = asyncio.Semaphore(2)
    observer, providers = telemetry.setup()
    try:
        ec = ExperimentClient(config.GEN_ENDPOINT, tenant_id=config.CLOUD_TENANT,
                              ingest_token=config.CLOUD_TOKEN, grafana_url=config.GRAPH_URL)
        async with httpx.AsyncClient(base_url=config.OPS_URL, headers={'X-Service-Token': config.SERVICE_TOKEN}, timeout=40) as http:
            async def request(method, path, body=None):
                response = await http.request(method, path, json=body)
                response.raise_for_status()
                return response.json()

            async def dispatch(ctx, name, arguments, callid):
                return await request('POST', '/internal/tools/' + name,
                                     {'context': ctx, 'arguments': arguments, 'call_id': callid})

            with Experiment(ec, name=f'ParcelDesk {args.suite} {version}', suite=suite,
                            candidate=Candidate(agent_name='parceldesk-replacement', agent_version=version,
                                                prompt_version=version, model_provider=config.PROVIDER, model_name=config.MODEL),
                            planned_trial_count=len(case_rows) * trials, online_evaluations_enabled=False,
                            default_evaluator=Evaluator('parceldesk-business-verifier', '2')) as exp:
                report['experiment_id'] = exp.experiment_id
                report['evidence_ref'] = exp.url
                save_report()

                async def one(case, attempt):
                    async with sem:
                        rid, cid = str(uuid.uuid4()), str(uuid.uuid4())
                        ctx = {'demo_run_id': rid, 'conversation_id': cid, 'customer_id': 'C1',
                               'business_date': '2026-09-15', 'fixture_revision': 'v1', 'agent_version': version,
                               'traffic_kind': 'experiment', 'scenario': case['scenario']}
                        state = {'conversation_id': cid, 'order_id': case['order_id'], 'messages': [],
                                 'model_messages': [], 'status': 'open', 'agent_version': version,
                                 'package_path': str(frozen_path)}
                        async with isolated_trial(request, ctx, case['order_id'], case['scenario']):
                            with exp.trial(case['id'], attempt=attempt) as trial:
                                trial.bind_conversation(cid)
                                try:
                                    with trace.get_tracer('parceldesk-evals').start_as_current_span('evaluate replacement') as span:
                                        trial.bind_trace(f'{span.get_span_context().trace_id:032x}')
                                        async with aclosing(run_turn(observer, ToolGateway(observer, dispatch), ctx, state, case['message'])) as execution:
                                            async for kind, payload in execution:
                                                pass
                                except Exception as error:
                                    state['status'], state['error_type'] = 'error', type(error).__name__
                                ledger = await request('GET', f'/internal/runs/{rid}/evidence')
                                ledger['orders'] = (await request('GET', f'/internal/orders?run_id={rid}&customer_id=C1'))['orders']
                                score = verify(state, ledger, case)
                                trial.final_score(score.primary_passed, passed=score.primary_passed, explanation=score.explanation)
                                for check in ['correctness_passed', 'task_completed', 'unsafe_attempt', 'prevention_passed', 'false_refusal']:
                                    value = getattr(score, check)
                                    trial.check_score(check, passed=(not value if check in ('unsafe_attempt', 'false_refusal') else value), value=value)
                                report['cases'].append({'case_id': case['id'], 'attempt': attempt, 'run_id': rid,
                                                        'conversation_id': cid, 'trial_id': trial.trial_id,
                                                        'score': score.to_dict(), 'state': state, 'ledger': ledger})
                                report['completed_cases'] += 1
                                save_report()
                                print(json.dumps({'case': case['id'], 'attempt': attempt, 'passed': score.primary_passed,
                                                  'unsafe': score.unsafe_attempt}), flush=True)

                async with asyncio.timeout(600):
                    await run_trials(one(case, attempt + 1) for case in case_rows for attempt in range(trials))
            report['status'] = 'completed'
            report['accepted'] = (all(c['score']['primary_passed'] for c in report['cases'])
                                  and report['completed_cases'] == len(case_rows) * trials)
            report['native_report_status'] = 'pending_host_gcx_readback'
            save_report()
    except BaseException:
        report['status'] = 'errored'
        report['accepted'] = False
        save_report()
        raise
    finally:
        try:
            await shutdown_exporters(observer, providers)
        except BaseException:
            report['status'] = 'errored'
            report['accepted'] = False
            report['exporter_shutdown_failed'] = True
            save_report()
            raise
    print(json.dumps({key: value for key, value in report.items() if key not in ('cases', 'native_report')}))
    return 0 if report['accepted'] else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate')
    parser.add_argument('--suite', choices=['smoke', 'full', 'heldout'], default='smoke')
    parser.add_argument('--trials', type=int)
    parser.add_argument('--output', default=str(ROOT / 'runs/evaluation.json'))
    parser.add_argument('--max-calls', type=int, default=216)
    sys.exit(asyncio.run(run(parser.parse_args())))
