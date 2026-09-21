import json,subprocess,pathlib,tempfile
root=pathlib.Path(__file__).resolve().parents[1]
for c in json.loads((root/'fixtures/cases.json').read_text()):
 data={'test_case_id':c['id'],'name':c['id'],'category':c['category'],'input':c,'expected':{'proposal':c['expect_proposal']},'weight':1}
 f=root/'runs/case-upsert.json';f.write_text(json.dumps(data))
 r=subprocess.run(['gcx','--context','demotests_gcloud','agento11y','experiments','test-suites','cases','upsert','parceldesk-replacement','v1','-f',str(f),'-o','json'],capture_output=True,text=True)
 if r.returncode:raise RuntimeError(r.stderr)
 print(c['id'])
r=subprocess.run(['gcx','--context','demotests_gcloud','agento11y','experiments','test-suites','versions','publish','parceldesk-replacement','v1','-o','json'],capture_output=True,text=True);print(r.stdout);r.check_returncode()
