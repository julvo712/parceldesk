import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('scoped_hook',Path(__file__).resolve().parents[1]/'coding/scoped_hook.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_only_demo_workspace_is_exported(tmp_path):
    root=tmp_path/'demo';root.mkdir()
    assert module.in_scope({'workspace_roots':[str(root)],'cwd':str(root/'.worktrees/meeting')},root)
    assert not module.in_scope({'workspace_roots':[str(tmp_path/'unrelated')]},root)
    assert not module.in_scope({'workspace_roots':[str(root),str(tmp_path/'unrelated')]},root)
    assert not module.in_scope({},root)
    assert not module.in_scope({'cwd':str(root/'../unrelated')},root)

def test_symlink_cannot_expand_capture_scope(tmp_path):
    root=tmp_path/'demo';root.mkdir();other=tmp_path/'other';other.mkdir()
    (root/'linked').symlink_to(other,target_is_directory=True)
    assert not module.in_scope({'cwd':str(root/'linked')},root)
