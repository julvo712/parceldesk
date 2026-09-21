"""A dirty worktree must never be presented as the clean GitHub commit."""
import importlib.util
from pathlib import Path
import subprocess
import pytest

spec = importlib.util.spec_from_file_location('runtime', Path(__file__).resolve().parents[1]/'runtime.py')
runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)


def test_clean_dirty_and_untracked_source_identity(tmp_path):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid')
    (tmp_path/'app.py').write_text('print(1)\n'); git('add', '.'); git('commit', '-m', 'baseline')
    clean = runtime.identity(tmp_path)
    assert len(clean['GIT_COMMIT']) == 40
    git('tag', 'v0.1.0'); assert runtime.identity(tmp_path)['SERVICE_VERSION'] == 'v0.1.0'
    (tmp_path/'app.py').write_text('print(2)\n')
    with pytest.raises(RuntimeError, match='Commit'): runtime.identity(tmp_path)
    dirty = runtime.identity(tmp_path, allow_dirty=True)
    assert dirty['GIT_COMMIT'] == '' and '-dirty-' in dirty['SERVICE_VERSION']
    git('checkout', '--', 'app.py'); (tmp_path/'new.py').write_text('print(3)\n')
    with pytest.raises(RuntimeError): runtime.identity(tmp_path)
