.PHONY: install lint fmt test run clean

install:
	pip install -e ".[dev]"

lint:
	ruff check src/ api/

fmt:
	ruff check --fix src/ api/

test:
	LUMI_OFFLINE=1 python -m pytest -q

run:
	streamlit run app.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
