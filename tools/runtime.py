#!/usr/bin/env python3
"""Run only this Compose project with an honest, reproducible build identity."""
from __future__ import annotations
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def identity(root=ROOT, allow_dirty=False):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    sha = git('rev-parse', 'HEAD')
    dirty = bool(git('status', '--porcelain', '--untracked-files=normal'))
    if dirty and not allow_dirty:
        raise RuntimeError('Commit the source before a versioned comparison, or use --allow-dirty for development.')
    tag = subprocess.run(['git', 'describe', '--tags', '--exact-match', 'HEAD'], cwd=root, capture_output=True, text=True)
    version = tag.stdout.strip() if tag.returncode == 0 else sha[:12]
    if dirty:
        version += '-dirty-' + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return {'SERVICE_VERSION': version, 'GIT_COMMIT': '' if dirty else sha,
            'SERVICE_REPOSITORY': 'https://github.com/julvo712/parceldesk'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['up', 'identity'])
    parser.add_argument('--allow-dirty', action='store_true')
    args = parser.parse_args()
    build = identity(allow_dirty=args.allow_dirty)
    if args.action == 'identity':
        print(json.dumps(build, indent=2)); return
    spec = importlib.util.spec_from_file_location('release_manager', ROOT/'release/manage.py')
    manager = importlib.util.module_from_spec(spec); spec.loader.exec_module(manager)
    env = {**os.environ, **build}
    subprocess.run(manager.compose('up', '--detach', '--build', '--wait', '--wait-timeout', '180'), cwd=ROOT, env=env, check=True)
    folder = ROOT/'runs/foundation'; folder.mkdir(parents=True, exist_ok=True)
    (folder/'deployed-build.json').write_text(json.dumps({**build, 'deployed_at': dt.datetime.now(dt.timezone.utc).isoformat()}, indent=2)+'\n')
    print(json.dumps(build, indent=2))


if __name__ == '__main__':
    main()
