import sys
from types import SimpleNamespace
from parceldesk import profiling


def test_worker_profiling_has_version_and_source_but_no_credentials(monkeypatch):
    captured={}
    sdk=SimpleNamespace(configure=lambda **kwargs:captured.update(kwargs),shutdown=lambda:None)
    monkeypatch.setitem(sys.modules,'pyroscope',sdk)
    monkeypatch.setenv('PYROSCOPE_SERVER_ADDRESS','http://alloy:4040')
    monkeypatch.setenv('SERVICE_VERSION','v0.2.0')
    monkeypatch.setenv('GIT_COMMIT','a'*40)
    monkeypatch.setenv('SERVICE_REPOSITORY','https://github.com/example/parceldesk')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_HEADERS','must-not-be-forwarded')
    assert profiling.start() is sdk
    assert captured['mem_enabled'] and captured['oncpu']
    assert captured['tags']['service_git_ref']=='a'*40
    assert captured['tags']['service_version']=='v0.2.0'
    assert 'http_headers' not in captured and 'basic_auth_password' not in captured


def test_unconfigured_profiler_does_not_start(monkeypatch):
    monkeypatch.delenv('PYROSCOPE_SERVER_ADDRESS',raising=False)
    assert profiling.start() is None
