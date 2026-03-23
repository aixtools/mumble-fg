PYTHON ?= python3

precheck:
	@./scripts/precheck.sh --message "$${COMMIT_MSG:?Set COMMIT_MSG with a Conventional Commit subject}"

