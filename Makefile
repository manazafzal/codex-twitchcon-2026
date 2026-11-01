.PHONY: check eval demo
check:
	ruff check .
	pytest -q
eval:
	thoughtquake eval
demo:
	thoughtquake demo --mock
