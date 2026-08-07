al-%:
	uv sync --reinstall-package stellarator
	uv run $(shell find examples -name "al_$*_*.py")