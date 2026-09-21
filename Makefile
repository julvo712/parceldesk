SHELL := /bin/bash
.DEFAULT_GOAL := help
CONTEXT ?= demotests_gcloud
CLOUD_CONFIG ?= release/cloud-config.example.json
RUN ?= meeting-001
TOOL ?= claude_code
SUITE ?= smoke
VERSION ?= 0.1.0
CHECK_SUITE ?= full
COMPOSE := docker compose --project-name parceldesk --file $(CURDIR)/compose.yaml
TEST_COMPOSE := docker compose --project-name parceldesk-tests --file $(CURDIR)/release/compose.test.yaml
PYTHONPATH_TEST := $(CURDIR)/apps/agent/src:$(CURDIR)/tools:$(CURDIR)
.PHONY: help install up down doctor test test-operations test-agent test-web test-browser test-release test-observer smoke eval eval-full faults demo demo-prepare demo-review demo-submit demo-evaluate demo-activate demo-reset dashboards release images clean-owned acceptance release-check
help:
	@printf '%s\n' 'ParcelDesk commands:' '  make install CONTEXT=... CLOUD_CONFIG=...' '  make up / doctor / demo / smoke' '  make test / test-browser' '  make eval SUITE=smoke|full|heldout' '  make demo-prepare RUN=meeting-001 TOOL=claude_code' '  make demo-review / demo-submit / demo-evaluate / demo-activate / demo-reset RUN=...' '  make faults / dashboards / release' 'See README.md and docs/presenter-onboarding.md.'
install:
	python3 release/manage.py install --context "$(CONTEXT)" --cloud-config "$(CLOUD_CONFIG)"
up:
	python3 -c 'import importlib.util; s=importlib.util.spec_from_file_location("manager","release/manage.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.run(m.compose("up","--detach","--build","--wait","--wait-timeout","180")); print("ParcelDesk started; run make doctor")'
down:
	python3 -c 'import importlib.util; s=importlib.util.spec_from_file_location("manager","release/manage.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.run(m.compose("stop"))'
doctor:
	python3 release/manage.py doctor --context "$(CONTEXT)"
test: test-operations test-agent test-web test-observer test-release
test-operations:
	python3 release/test_operations.py
test-agent:
	PYTHONPATH="$(PYTHONPATH_TEST)" uv run --directory apps/agent pytest tests "$(CURDIR)/tools/tests" "$(CURDIR)/evals/test_verifiers.py"
test-web:
	npm --prefix apps/web ci
	npm --prefix apps/web test
	npm --prefix apps/web run build
test-browser:
	npm --prefix apps/web run test:browser
test-observer:
	python3 -m unittest discover -s tools/observer -p 'test_*.py'
test-release:
	python3 -m unittest discover -s release -p 'test_*.py'
smoke:
	python3 release/verify_runtime.py
eval:
	$(COMPOSE) exec -T agent-api python /app/evals/runner.py --suite "$(SUITE)" --output /app/runs/evaluation-$(SUITE).json
eval-full:
	$(MAKE) eval SUITE=full
faults:
	python3 tools/observer/rehearse_faults.py
demo:
	@printf '%s\n' 'Customer: http://localhost:3100' 'Presenter: http://localhost:3101' 'Grafana: https://demotests.grafana.net/d/pd-overview' 'Run make doctor before the meeting. Presenter flow: docs/presenter-onboarding.md'
demo-prepare:
	PYTHONPATH=tools python3 -m parceldesk_demo.cli prepare --run "$(RUN)" --tool "$(TOOL)"
demo-review:
	PYTHONPATH=tools python3 -m parceldesk_demo.cli check-diff --run "$(RUN)" --reviewed
demo-submit:
	PYTHONPATH=tools python3 -m parceldesk_demo.cli submit --run "$(RUN)"
demo-evaluate:
	PYTHONPATH=tools python3 -m parceldesk_demo.cli evaluate --run "$(RUN)" --suite "$(SUITE)"
demo-activate:
	PYTHONPATH=tools python3 -m parceldesk_demo.cli activate --run "$(RUN)"
demo-reset:
	PYTHONPATH=tools python3 -m parceldesk_demo.cli reset --run "$(RUN)"
dashboards:
	python3 infra/grafana/manage.py deploy --context "$(CONTEXT)"
release:
	python3 release/capture_images.py
	python3 release/build.py --version "$(VERSION)"
images:
	python3 release/build.py --version "$(VERSION)" --images
clean-owned:
	python3 release/manage.py uninstall --owned-only

acceptance release-check:
	python3 release/check.py --suite "$(CHECK_SUITE)"
