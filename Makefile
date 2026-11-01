.PHONY: check eval demo
check:
	ruff check .
	mypy src/nous/engine src/nous/model src/nous/concepts src/nous/evaluation.py
	pytest -q
eval:
	nous eval
demo:
	nous demo --mock
