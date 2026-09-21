"""Host-only bounded coding lifecycle. No shell evaluation and no web execution."""
import ast
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from .development.events import DevelopmentLedger, utcnow

PACKAGE_FILES = ('agents/replacement/system.md', 'agents/replacement/context.py')
SAFE_IMPORTS = {'json', 're', 'typing'}
SAFE_ATTRIBUTES = {'get','items','keys','values','join','format','format_map','strip','lstrip','rstrip','lower','upper','replace','split','startswith','endswith','search','match','fullmatch','sub','escape','findall','dumps','loads','Dict','List','Optional','Mapping','Sequence','Any'}
FORBIDDEN_CALLS = {'eval','exec','compile','open','__import__','getattr','setattr','delattr','globals','locals','vars','input','breakpoint'}
UNITTEST_ASSERTIONS = {'assertEqual','assertNotEqual','assertTrue','assertFalse',
    'assertIs','assertIsNot','assertIsNone','assertIsNotNone','assertIn','assertNotIn',
    'assertIsInstance','assertNotIsInstance','assertAlmostEqual','assertNotAlmostEqual',
    'assertGreater','assertGreaterEqual','assertLess','assertLessEqual','assertRegex',
    'assertNotRegex','assertCountEqual','assertSequenceEqual','assertListEqual',
    'assertTupleEqual','assertSetEqual','assertDictEqual','assertMultiLineEqual'}


def has_regression_assertion(test):
    """Recognize pytest/unittest checks, excluding obvious constant-only stubs.

    This is a boundary check, not proof of test quality; execution and operator
    review still gate acceptance. Message arguments never count as evidence.
    """
    def dynamic(expression):
        return any(isinstance(n,(ast.Name,ast.Call,ast.Attribute,ast.Subscript))
                   for n in ast.walk(expression))
    def method(call):
        return (call.func.attr if isinstance(call,ast.Call)
                and isinstance(call.func,ast.Attribute)
                and isinstance(call.func.value,ast.Name)
                and call.func.value.id=='self' else None)
    unary={'assertTrue','assertFalse','assertIsNone','assertIsNotNone'}
    for node in ast.walk(test):
        if isinstance(node,ast.Assert) and dynamic(node.test):return True
        name=method(node)
        if name in UNITTEST_ASSERTIONS:
            count=1 if name in unary else 2
            if len(node.args)>=count and any(dynamic(a) for a in node.args[:count]):return True
        if name in {'assertRaises','assertRaisesRegex'}:
            offset=1 if name=='assertRaises' else 2
            if len(node.args)>offset and dynamic(node.args[offset]):return True
        if isinstance(node,(ast.With,ast.AsyncWith)):
            if any(method(item.context_expr) in {'assertRaises','assertRaisesRegex'}
                   for item in node.items):
                if any(isinstance(n,(ast.Call,ast.Raise)) for statement in node.body
                       for n in ast.walk(statement)):return True
    return False


def git(path, *args):
    result=subprocess.run(['git','-C',str(path),*args],capture_output=True,text=True,timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'Git operation failed')
    return result.stdout


@dataclass(frozen=True)
class DiffReport:
    allowed: bool
    changed_paths: tuple
    rejected_paths: tuple
    reasons: tuple
    baseline_commit: str
    agent_version: str
    diff_sha256: str
    def to_dict(self):return asdict(self)


def package_version(path):
    base=Path(path)
    return hashlib.sha256((base/PACKAGE_FILES[0]).read_bytes()+b'\0'+(base/PACKAGE_FILES[1]).read_bytes()).hexdigest()[:16]


def validate_context(source):
    tree=ast.parse(source)
    if not any(isinstance(n,ast.FunctionDef) and n.name=='build_context' for n in tree.body):
        raise ValueError('Pure context module must define build_context')
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            names=[n.name for n in node.names] if isinstance(node,ast.Import) else [node.module or '']
            if any(n.split('.')[0] not in SAFE_IMPORTS for n in names) or getattr(node,'level',0):
                raise ValueError('Context builder imports must be pure approved standard-library modules')
        if isinstance(node,ast.Call) and ((isinstance(node.func,ast.Name) and node.func.id in FORBIDDEN_CALLS) or (isinstance(node.func,ast.Attribute) and node.func.attr in FORBIDDEN_CALLS)):
            raise ValueError('Context builder cannot use dynamic execution, filesystem or reflection')
        if isinstance(node,ast.Attribute) and node.attr not in SAFE_ATTRIBUTES:
            raise ValueError('Context builder attribute is outside the pure string/JSON allowlist')
        if isinstance(node,ast.Name) and node.id.startswith('__') and node.id not in ('__name__',):
            raise ValueError('Context builder cannot use dunder names')
        if isinstance(node,(ast.Global,ast.Nonlocal)):
            raise ValueError('Context builder must not mutate global state')
    return tree


def check_diff(path, baseline='HEAD') -> DiffReport:
    path=Path(path).resolve();commit=git(path,'rev-parse','--verify',baseline+'^{commit}').strip()
    raw=git(path,'diff','--name-status','-z','--find-renames',commit,'--');parts=raw.split('\0');changes=[];i=0
    while i<len(parts) and parts[i]:
        status=parts[i];i+=1;name=parts[i];i+=1
        if status.startswith(('R','C')):
            new=parts[i];i+=1;changes.extend([(status,name),(status,new)])
        else:changes.append((status,name))
    for name in git(path,'ls-files','--others','--exclude-standard','-z').split('\0'):
        if name:changes.append(('A',name))
    rejected=[];reasons=[]
    for status,name in changes:
        file=path/name;reason=None
        if file.is_symlink() or (file.exists() and not file.resolve().is_relative_to(path)):
            reason='Symlinks and paths outside the worktree are forbidden'
        elif name in PACKAGE_FILES:
            if status!='M':reason='Existing live package files may be modified, not deleted or renamed'
        elif re.fullmatch(r'tests/live/test_[A-Za-z0-9_]+\.py',name):
            if status!='A':reason='Regression tests must be newly added; existing tests cannot be changed/deleted'
            elif file.exists():
                try:
                    tree=ast.parse(file.read_text())
                    tests=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_')]
                    if not tests or any(not has_regression_assertion(t) for t in tests):reason='Every regression test must contain a real assertion'
                    if any(isinstance(n,ast.Attribute) and n.attr in ('skip','skipif','xfail') for n in ast.walk(tree)):reason='Regression tests cannot be skipped or marked expected-fail'
                except (SyntaxError,UnicodeError):reason='Regression test does not parse'
        else:reason='Outside the live prompt/context and added-regression-test boundary'
        if reason:rejected.append(name);reasons.append(f'{name}: {reason}')
    context=path/PACKAGE_FILES[1]
    try:validate_context(context.read_text())
    except (SyntaxError,ValueError,UnicodeError,OSError) as exc:
        if PACKAGE_FILES[1] not in rejected:rejected.append(PACKAGE_FILES[1])
        reasons.append(str(exc))
    try:version=package_version(path)
    except OSError:version='missing'
    fingerprint=hashlib.sha256()
    for name in sorted({n for _,n in changes}):
        fingerprint.update(name.encode()+b'\0')
        file=path/name
        if file.exists() and file.is_file() and not file.is_symlink():fingerprint.update(file.read_bytes())
        fingerprint.update(b'\0')
    return DiffReport(not rejected,tuple(sorted({n for _,n in changes})),tuple(sorted(set(rejected))),tuple(reasons),commit,version,fingerprint.hexdigest())


def atomic_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def read_native_report(experiment_id, agent_version, expected_trials, context='demotests_gcloud'):
    """Read native final verdicts using host gcx credentials, never container secrets."""
    if not re.fullmatch(r'exp-[A-Za-z0-9_-]+', experiment_id):
        raise ValueError('Invalid native experiment ID')
    command=['gcx','--context',context,'agento11y','experiments','get-report',experiment_id,'-o','json']
    result=subprocess.run(command,capture_output=True,text=True,timeout=45)
    if result.returncode:
        raise RuntimeError('Native experiment report is unavailable; activation remains blocked')
    report=json.loads(result.stdout);experiment=report.get('experiment',{});summary=report.get('summary',{})
    if experiment.get('experiment_id')!=experiment_id or experiment.get('candidate',{}).get('agent_version')!=agent_version:
        raise ValueError('Native experiment does not match this candidate')
    if experiment.get('status')!='completed' or experiment.get('result_status')!='ready':
        raise ValueError('Native experiment results are pending; activation remains blocked')
    trials=[t for row in report.get('rows',[]) for t in row.get('trials',[])]
    ids=[t.get('trial',{}).get('trial_id') for t in trials]
    if len(trials)!=expected_trials or len(set(ids))!=expected_trials or None in ids:
        raise ValueError('Native trial count/identity does not match completed local evidence')
    if summary.get('completed_count')!=expected_trials:
        raise ValueError('Native report has incomplete completed trial coverage')
    # Native pass_denominator counts test cases (first-attempt aggregate), not trials.
    if summary.get('pass_denominator')!=len(report.get('rows',[])):
        raise ValueError('Native report has incomplete test-case summary coverage')
    passed=[]
    for entry in trials:
        trial=entry.get('trial',{});score=entry.get('final_score',{})
        if trial.get('status')!='completed' or score.get('score_key') not in ('final','primary_verdict') or not isinstance(score.get('passed'),bool):
            raise ValueError('Every native trial requires a completed primary verdict')
        if score.get('evaluator_id')!='parceldesk-business-verifier':
            raise ValueError('Unexpected primary evaluator')
        passed.append(score['passed'])
    return {'verified':True,'accepted':all(passed),'verified_at':utcnow(),'report':report}


class DemoWorkflow:
    def __init__(self, repo, ledger=None, state_dir=None, native_reader=None):
        self.repo=Path(repo).resolve()
        self.native_reader=native_reader or read_native_report
        self.state=Path(state_dir or self.repo/'runs'/'development').resolve()
        self.state.mkdir(parents=True,exist_ok=True)
        self.ledger=ledger or DevelopmentLedger(os.getenv('PARCELDESK_DEVELOPMENT_DB',str(self.state/'development.sqlite')))

    def runfile(self, run):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',run):raise ValueError('Run must be a short safe slug')
        return self.state/'runs'/f'{run}.json'

    def load(self, run):
        return json.loads(self.runfile(run).read_text())

    def event(self, data, kind, payload, identity):
        event={'event_id':f'{data["run"]}:{identity}','task_id':data['task_id'],'event':kind,
               'source_timestamp':utcnow(),'actor':data['actor'],'tool':data.get('tool'),
               'evidence_ref':str(self.runfile(data['run'])),'synthetic':False,'payload':payload}
        # Repeating the same transition reuses its original immutable event time.
        old=next((e for e in self.ledger.events(data['task_id']) if e['event_id']==event['event_id']),None)
        if old and (old['event']!=kind or old['payload']!=payload):
            raise ValueError('Transition identity already has different immutable evidence')
        return self.ledger.append(old or event)

    def prepare(self, run, baseline='parceldesk-baseline', actor='presenter', tool=None):
        file=self.runfile(run)
        if file.exists():
            data=self.load(run)
            self.event(data,'task_started',{'baseline_commit':data['baseline_commit'],'worktree':data['worktree']},'started')
            return data
        commit=git(self.repo,'rev-parse','--verify',baseline+'^{commit}').strip()
        path=self.repo/'.worktrees'/run
        if path.exists():raise ValueError('Worktree path already exists without this run manifest')
        path.parent.mkdir(parents=True,exist_ok=True)
        git(self.repo,'worktree','add','--detach',str(path),commit)
        data={'schema_version':1,'run':run,'task_id':f'demo:{run}','actor':actor,'tool':tool,
              'baseline_commit':commit,'baseline_ref':baseline,'worktree':str(path),'created_at':utcnow(),
              'baseline_agent_version':package_version(path),'status':'prepared','candidate_history':[]}
        atomic_json(file,data)
        self.event(data,'task_started',{'baseline_commit':commit,'worktree':str(path)},'started')
        return data

    def inspect(self, run, reviewed=False):
        data=self.load(run);report=check_diff(data['worktree'],data['baseline_commit'])
        if reviewed:
            if not report.allowed:raise ValueError('Cannot review a candidate that violates the edit boundary')
            if not report.changed_paths:raise ValueError('Candidate contains no change')
            data['review']={'diff_sha256':report.diff_sha256,'agent_version':report.agent_version,'reviewed_at':utcnow(),'reviewer':data['actor']}
            atomic_json(self.runfile(run),data)
        return report

    def submit(self, run):
        data=self.load(run);report=self.inspect(run)
        if not report.allowed:raise ValueError('; '.join(report.reasons))
        if not report.changed_paths:raise ValueError('Candidate contains no change')
        review=data.get('review',{})
        if review.get('diff_sha256')!=report.diff_sha256:raise ValueError('Exact candidate diff needs review using check-diff --reviewed')
        candidate=report.agent_version
        if candidate==data['baseline_agent_version']:
            raise ValueError('The runtime package must change; test-only edits do not create a new agent version')
        dest=self.state/'packages'/candidate
        if not dest.exists():
            dest.mkdir(parents=True)
            for file in PACKAGE_FILES:shutil.copy2(Path(data['worktree'])/file,dest/Path(file).name)
            atomic_json(dest/'manifest.json',{'agent_version':candidate,'baseline_commit':data['baseline_commit'],'diff_sha256':report.diff_sha256,'created_at':utcnow()})
        data['candidate_id']=candidate;data['candidate_path']=str(dest);data['status']='submitted'
        if candidate not in data['candidate_history']:data['candidate_history'].append(candidate)
        atomic_json(self.runfile(run),data)
        self.event(data,'candidate_submitted',{'candidate_id':candidate,'diff_sha256':report.diff_sha256},f'{candidate}:submitted')
        return data

    def evaluate(self, run, suite='smoke', evaluator=None):
        data=self.submit(run)
        if suite not in ('smoke','full'):raise ValueError('Suite must be smoke or full')
        output=self.state/'evaluations'/f'{run}-{data["candidate_id"]}-{suite}.json';output.parent.mkdir(parents=True,exist_ok=True)
        if evaluator is None:
            raise ValueError('Configure an actual evaluator command; missing native experiment evidence cannot pass')
        # Explicit argv adapter, never shell=True or a command taken from a web request.
        if evaluator==['docker-compose']:
            candidate_arg='/app/'+str(Path(data['candidate_path']).relative_to(self.repo))
            output_arg='/app/'+str(output.relative_to(self.repo))
            command=['docker','compose','--project-name','parceldesk','--file',str(self.repo/'compose.yaml'),'exec','-T','agent-api','python','/app/evals/runner.py','--candidate',candidate_arg,'--suite',suite,'--output',output_arg]
        else:
            command=[*evaluator,'--candidate',data['candidate_path'],'--suite',suite,'--output',str(output)]
        result=subprocess.run(command,cwd=self.repo,text=True,capture_output=True,timeout=660)
        if result.returncode not in (0,2):raise RuntimeError('Evaluator command failed; candidate remains inactive')
        if not output.exists():raise RuntimeError('Evaluator produced no report; candidate remains inactive')
        return self.record_evaluation(run,output)

    def record_evaluation(self, run, report_path):
        data=self.load(run);report=json.loads(Path(report_path).read_text())
        candidate=data.get('candidate_id')
        if report.get('agent_version')!=candidate:raise ValueError('Evaluation is not for this candidate version')
        if report.get('status')!='completed' or not report.get('experiment_id') or not report.get('evidence_ref'):
            raise ValueError('Completed native experiment evidence is required')
        if report.get('suite') not in ('smoke','full'):
            raise ValueError('Evaluation must identify its smoke or full suite')
        for key in ('provider','model','evaluator_version','suite_version'):
            if not isinstance(report.get(key),str) or not report[key]:
                raise ValueError('Evaluation must identify its provider, model and verifier/suite versions')
        minimum={'smoke':6,'full':36}[report['suite']]
        if not isinstance(report.get('completed_cases'),int) or report['completed_cases']<minimum:
            raise ValueError(f'Evaluation requires at least {minimum} completed trials')
        if 'cases' in report and len(report['cases'])!=report['completed_cases']:
            raise ValueError('Reported trial count does not match trial evidence')
        if report.get('accepted') is True and 'cases' in report and not all(c.get('score',{}).get('primary_passed') is True for c in report['cases']):
            raise ValueError('Accepted report contains a failed primary verdict')
        native=self.native_reader(report['experiment_id'],candidate,report['completed_cases'])
        if native.get('verified') is not True:
            raise ValueError('Native experiment verification did not complete')
        native_experiment=native.get('report',{}).get('experiment',{})
        native_candidate=native_experiment.get('candidate',{})
        if (native_candidate.get('model_provider')!=report['provider']
                or native_candidate.get('model_name')!=report['model']):
            raise ValueError('Native experiment model/provider differs from local evaluation')
        if native_experiment.get('suite_version')!=report['suite_version']:
            raise ValueError('Native experiment suite version differs from local evaluation')
        versions={str(t.get('final_score',{}).get('evaluator_version'))
                  for row in native['report'].get('rows',[]) for t in row.get('trials',[])}
        if versions!={report['evaluator_version']}:
            raise ValueError('Native primary evaluator version differs from local evaluation')
        report['native_report_status']='verified'
        report['native_verification']=native
        report['accepted']=report.get('accepted') is True and native.get('accepted') is True
        result='passed' if report['accepted'] else 'rejected'
        atomic_json(report_path,report)
        digest=hashlib.sha256(Path(report_path).read_bytes()).hexdigest()
        data['evaluation']={**report,'report_path':str(Path(report_path).resolve()),'report_sha256':digest};data['status']='evaluated'
        self.event(data,'candidate_evaluated',{'candidate_id':candidate,'result':result,'experiment_id':report['experiment_id'],'provider':report['provider'],'model':report['model'],'evaluator_version':report['evaluator_version'],'suite_version':report['suite_version'],'evidence_ref':report['evidence_ref']},f'{candidate}:evaluated:{report["experiment_id"]}')
        atomic_json(self.runfile(run),data)
        return data

    def activate(self, run):
        data=self.load(run);report=self.inspect(run);evaluation=data.get('evaluation',{})
        if not report.allowed or data.get('review',{}).get('diff_sha256')!=report.diff_sha256:
            raise ValueError('Candidate changed since review')
        if report.agent_version!=data.get('candidate_id') or evaluation.get('accepted') is not True or evaluation.get('status')!='completed' or evaluation.get('native_report_status')!='verified':
            raise ValueError('Activation requires the reviewed candidate and a completed accepted experiment')
        source=Path(evaluation['report_path'])
        if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest()!=evaluation.get('report_sha256'):
            raise ValueError('Evaluation evidence changed or disappeared')
        package=Path(data['candidate_path'])
        if hashlib.sha256((package/'system.md').read_bytes()+b'\0'+(package/'context.py').read_bytes()).hexdigest()[:16]!=data['candidate_id']:
            raise ValueError('Immutable candidate package bytes changed')
        manifest={'run':run,'agent_version':data['candidate_id'],'package_path':data['candidate_path'],'baseline_commit':data['baseline_commit'],
                  'experiment_id':evaluation['experiment_id'],'activated_at':utcnow(),'mode':'accepted',
                  'provider':evaluation['provider'],'model':evaluation['model'],
                  'evaluator_version':evaluation['evaluator_version'],'suite':evaluation['suite'],'suite_version':evaluation['suite_version']}
        self.event(data,'candidate_accepted',{'candidate_id':data['candidate_id'],'experiment_id':evaluation['experiment_id']},f'{data["candidate_id"]}:accepted')
        atomic_json(self.state/'active.json',manifest)
        data['status']='active';atomic_json(self.runfile(run),data)
        return manifest

    def reset(self, run):
        data=self.load(run)
        manifest={'run':run,'agent_version':data['baseline_agent_version'],'baseline_commit':data['baseline_commit'],'mode':'baseline','reset_at':utcnow()}
        atomic_json(self.state/'active.json',manifest)
        data['status']='reset';atomic_json(self.runfile(run),data)
        # Never git reset/clean/remove: all coding diffs, worktrees and evidence survive.
        return manifest
