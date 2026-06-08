# PageDrop test gates — cumulative through each phase (no venv activation needed)

.PHONY: test-phase1 test-phase2 test-phase3 test-phase4 test build-exe smoke-exe test-release

BUILD_EXE := uv run pyinstaller --noconfirm pagedrop.spec
PAGEDROP_EXE ?= ./dist/pagedrop/pagedrop

test-phase1:
	uv run python scripts/test_phase.py 1

test-phase2:
	uv run python scripts/test_phase.py 2

test-phase3:
	uv run python scripts/test_phase.py 3

test-phase4:
	uv run python scripts/test_phase.py 4

test:
	uv run python all_tests.py

test-all: test

build-exe:
	$(BUILD_EXE)

smoke-exe: build-exe
	./scripts/smoke_exe.sh

# Full suite before a release tag (exe smoke test is opt-in via PAGEDROP_EXE).
test-release:
	uv run pytest tests/ -v --ignore=tests/smoke/test_phase16_executable.py
	PAGEDROP_EXE=$(PAGEDROP_EXE) uv run pytest tests/smoke/test_phase16_executable.py -v
