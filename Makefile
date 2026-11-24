# Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
# SPDX-License-Identifier: GPL-2.0-only
#
# swarm-routing.github.io: the org's standard targets (swarm-routing/.github#11). Every org
# repo has these same target names, with this repo's own commands behind them;
# `org-sync check` verifies the names are present, never the recipes. Add
# repo-only targets at the end. `make help` lists everything with a `## ` note.

NS3_IMAGE ?= ghcr.io/swarm-routing/ns3-dev:latest-debug
PLATFORM  ?=
# container kind: the image's Dockerfile and its build arguments
DOCKERFILE ?= Dockerfile
BUILD_ARGS ?=

.DEFAULT_GOAL := help
.PHONY: help build test lint format check clean shell ci headers org-sync-check org-tools dist

help: ## list the targets
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z0-9_-]+:.*## /{printf "  %-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## build what this repo ships
	tools/build-site.sh build/site

test: ## the fast tests CI runs on every PR
	python3 tools/lock.py --self-test && python3 tools/check_hub.py --self-test && python3 tools/hub_data.py --self-test && python3 tools/images_data.py --self-test && python3 tools/render_hub.py --self-test
	python3 site/anthocnet/shell/inject.py --self-test && python3 tools/check_tokens.py --self-test && python3 tools/check_tokens.py
	node test/shell-search.test.mjs

lint: ## static checks, no changes
	shellcheck $$(git ls-files '*.sh') && actionlint

format: ## apply the formatters
	@echo "make format: nothing to do in this repo (kind site)"

clean: ## remove build outputs
	@echo "make clean: nothing to do in this repo (kind site)"

shell: ## an interactive shell in the dev image with this repo at /src
	@command -v docker >/dev/null || { echo "make shell: docker not found (Docker Desktop, Colima, or docker.io)" >&2; exit 127; }
	docker run --rm -it -v "$(CURDIR):/src" -w /src $(if $(PLATFORM),--platform $(PLATFORM)) $(NS3_IMAGE) bash

headers: org-tools ## licence headers (org rule 1)
	"$(ORG_DIR)/tools/checks/check-headers.sh" --dual tools/ .

check: lint test headers org-sync-check ## everything CI gates on

ci: check ## exactly what CI runs

# The release asset (swarm-routing/.github#636): the source tree at HEAD as
# swarm-routing.github.io-<version>.tar.gz, deterministic (git archive); the
# built site needs emsdk and a protocol checkout, and Pages serves it already.
# reusable-release.yml's build runs it at the release commit with
# RELEASE_VERSION set; locally it takes .cz.toml's version.
dist: ## the release asset: dist/swarm-routing.github.io-<version>.tar.gz
	@v="$${RELEASE_VERSION:-$$(python3 -I -c 'import tomllib; print(tomllib.load(open(".cz.toml", "rb"))["tool"]["commitizen"]["version"])')}" || exit $$?; \
	[ -n "$$v" ] || { echo "make dist: no version (RELEASE_VERSION or .cz.toml)" >&2; exit 1; }; \
	mkdir -p dist && git archive --format=tar.gz --prefix="swarm-routing.github.io-$$v/" -o "dist/swarm-routing.github.io-$$v.tar.gz" HEAD && \
	echo "dist/swarm-routing.github.io-$$v.tar.gz"

# org-sync:begin org-tools
# The org tooling (check-headers, org-sync): a shallow clone, refreshed to ORG_REF,
# by default the template commit .github/org-sync.lock pins, as CI checks (#586).
ORG_DIR   ?= $(HOME)/.cache/swarm-routing/dotgithub
ORG_REF   ?= $(or $(shell sed -nE 's/^commit = "([0-9a-f]{40})"[[:space:]]*$$/\1/p' .github/org-sync.lock 2>/dev/null),main)
# make pre-push TITLE='type(scope): subject': the PR title rule of reusable-pr-title.yml
export TITLE
TITLE_RE  := ^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([a-z0-9._/-]+\))?!?: [^A-Z ](.*[^ ])?$$

.PHONY: org-tools org-sync-check pre-push

org-tools:  # the same templates CI checks against: refreshed to ORG_REF every time
	@[ -d "$(ORG_DIR)/.git" ] || { git init -q "$(ORG_DIR)" && git -C "$(ORG_DIR)" remote add origin https://github.com/swarm-routing/.github; }
	@git -C "$(ORG_DIR)" fetch -q --depth 1 origin $(ORG_REF) && git -C "$(ORG_DIR)" checkout -q --detach FETCH_HEAD

org-sync-check: org-tools ## org-managed files match the org templates
	python3 -I "$(ORG_DIR)/tools/org-sync/org_sync.py" check .

pre-push: check ## before every push: make check, then TITLE='type(scope): subject' (the PR title)
	@[ -n "$$TITLE" ] || { echo "make pre-push: pass TITLE='<the PR title>'" >&2; exit 2; }
	@printf '%s\n' "$$TITLE" | grep -Eq '$(TITLE_RE)' || { echo "PR title is not a lowercase Conventional Commit: $$TITLE" >&2; exit 1; }
	@echo "pre-push: ok ($$TITLE)"

.PHONY: doctor
doctor: ## this machine's tools against the versions CI runs (the org's tools/versions.env, go.mod), and the hosts the network steps need
	@$(MAKE) -s org-tools || echo "doctor: could not refresh $(ORG_DIR) (offline?): using it as it is" >&2
	@"$(ORG_DIR)/tools/doctor/doctor.sh" .
# org-sync:end org-tools
