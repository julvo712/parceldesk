#!/usr/bin/env python3
"""Keep globally installed Cursor hooks scoped to this demo's workspaces."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]

def in_scope(payload, root=ROOT):
    roots=payload.get('workspace_roots') or []
    if not isinstance(roots,list):return False
    paths=[*roots]
    if payload.get('cwd'):paths.append(payload['cwd'])
    if not paths:return False
    try:
        # Mixed-workspace sessions are excluded; never export another project.
        return all(isinstance(p,str) and Path(p).is_absolute() and Path(p).resolve().is_relative_to(root.resolve()) for p in paths)
    except (OSError,ValueError,TypeError):return False

def main():
    raw=sys.stdin.buffer.read()
    try:payload=json.loads(raw)
    except (ValueError,TypeError):return 0
    if not isinstance(payload,dict) or not in_scope(payload):return 0
    return subprocess.run([str(ROOT/'tools/bin/agento11y'),'cursor','hook'],input=raw,timeout=25).returncode

if __name__=='__main__':raise SystemExit(main())
