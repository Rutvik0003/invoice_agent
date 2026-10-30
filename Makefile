# Thin wrapper around tasks.py so `make dev` works where make is installed.
# Activate the virtualenv first (or override: make dev PYTHON=.venv/bin/python).
PYTHON ?= python

.PHONY: install dev test build docker-build docker-run
install:
	$(PYTHON) tasks.py install
dev:
	$(PYTHON) tasks.py dev
test:
	$(PYTHON) tasks.py test
build:
	$(PYTHON) tasks.py build
docker-build:
	$(PYTHON) tasks.py docker-build
docker-run:
	$(PYTHON) tasks.py docker-run
