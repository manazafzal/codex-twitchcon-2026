.PHONY: check eval demo
check:
	ruff check .
	mypy src/thoughtquake/engine src/thoughtquake/model src/thoughtquake/concepts src/thoughtquake/evaluation.py
	pytest -q
eval:
	thoughtquake eval
demo:
	thoughtquake demo --mock
