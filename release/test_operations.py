#!/usr/bin/env python3
"""Run genuine PostgreSQL Go tests in a separately named, disposable project."""
import os,pathlib,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
 compose=['docker','compose','--project-name','parceldesk-tests','--file',str(ROOT/'release/compose.test.yaml')]
 try:
  subprocess.run(compose+['up','--detach','--wait','--wait-timeout','60'],check=True,cwd=ROOT)
  env=dict(os.environ,TEST_DATABASE_URL='postgres://postgres:local-tests-only@127.0.0.1:55439/parceldesk?sslmode=disable')
  subprocess.run(['go','test','-race','./...'],check=True,cwd=ROOT/'services/operations',env=env)
  subprocess.run(['go','vet','./...'],check=True,cwd=ROOT/'services/operations',env=env)
 finally:subprocess.run(compose+['down','--volumes'],check=False,cwd=ROOT)
if __name__=='__main__':main()
