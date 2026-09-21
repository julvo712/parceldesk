#!/usr/bin/env python3
"""Compare authentic ledger expectations with independently queried Cloud values."""
import argparse
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import sys
from manage import call,ROOT

def compare(context,expected):
 if not expected.get('source_evidence') or expected.get('synthetic',True):
  raise ValueError('Authentic source_evidence and synthetic=false are required')
 checks=expected.get('checks',[])
 if not checks:raise ValueError('At least one real expectation is required; missing evidence does not pass')
 results=[]
 for check in checks:
  expr=check['query']
  if '$' in expr:raise ValueError('Expectations must use concrete queries without dashboard macros')
  r=call(context,'metrics','query','-d',expected.get('datasource','grafanacloud-prom'),expr)
  values=r.get('data',{}).get('result',[])
  actual=float(values[0]['value'][1]) if len(values)==1 else None
  target=float(check['expected'])
  passed=actual is not None and math.isfinite(actual) and math.isclose(actual,target,rel_tol=check.get('relative_tolerance',1e-6),abs_tol=check.get('absolute_tolerance',1e-6))
  results.append(dict(name=check['name'],query=expr,expected=target,actual=actual,passed=passed))
 report=dict(checked_at=datetime.now(timezone.utc).isoformat(),source_evidence=expected['source_evidence'],context=context,checks=results,passed=all(x['passed'] for x in results))
 (ROOT/'evidence'/'values.json').write_text(json.dumps(report,indent=2)+'\n')
 return report

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--context',default='demotests_gcloud');p.add_argument('--expected',required=True,type=Path);a=p.parse_args()
 try:r=compare(a.context,json.loads(a.expected.read_text()));print(json.dumps(r,indent=2));sys.exit(0 if r['passed'] else 1)
 except (ValueError,KeyError,RuntimeError) as e:print(str(e),file=sys.stderr);sys.exit(1)
