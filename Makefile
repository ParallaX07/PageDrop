# PageDrop test gates — cumulative through each phase (no venv activation needed)

.PHONY: test-phase1 test-phase2 test-phase3 test-phase4 test build-exe smoke-exe test-release generate-icons build-installer

BUILD_EXE := uv run pyinstaller --noconfirm pagedrop.spec
PAGEDROP_EXE ?= ./dist/pagedrop

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

generate-icons:
	uv run --with pillow python scripts/generate_icons.py

# Windows only — requires Inno Setup 6+ (iscc).
build-installer:
	pwsh -File scripts/build_windows_installer.ps1

# Full suite before a release tag (exe smoke test is opt-in via PAGEDROP_EXE).
test-release:
	uv run pytest tests/ -v --ignore=tests/smoke/test_phase16_executable.py
	PAGEDROP_EXE=$(PAGEDROP_EXE) uv run pytest tests/smoke/test_phase16_executable.py -v
