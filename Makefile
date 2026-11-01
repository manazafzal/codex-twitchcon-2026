.PHONY: check eval demo paper
check:
	python -m nous.research.paper --check
	ruff check .
	mypy src/nous/engine src/nous/model src/nous/concepts src/nous/evaluation.py src/nous/research
	pytest -q
eval:
	nous eval
demo:
	nous demo
paper:
	python -m nous.research.paper
