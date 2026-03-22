.PHONY: test test-live lint fmt

test:
	pytest -m "not live and not slow" --tb=short -q

test-live:
	pytest --tb=short -q

lint:
	ruff check src/ tests/ scripts/

fmt:
	ruff format src/ tests/ scripts/
