# PageDrop test gates — cumulative through each phase (no venv activation needed)

.PHONY: test-phase1 test-phase2 test-phase3 test-phase4 test

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
