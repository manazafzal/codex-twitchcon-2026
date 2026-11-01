.PHONY: check eval demo
check:
	ruff check .
	pytest -q
eval:
	mindwars eval
demo:
	mindwars demo --mock
