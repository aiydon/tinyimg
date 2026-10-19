UV := uv


.PHONY: build check format lint sync test type


format:
	$(UV) format

lint:
	$(UV) run ruff check src tests scripts

type:
	$(UV) tool run ty check src/tinyimg

test:
	$(UV) run pytest -q

check: format lint type test

build:
	$(UV) build

sync:
	$(UV) sync
