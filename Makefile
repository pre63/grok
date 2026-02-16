SHELL := /bin/bash

OS := $(shell uname -s)

DEVICE=cpu

default: serve


venv:
	@test -d .venv || python3.12 -m venv .venv
	@. .venv/bin/activate && \
	pip install --upgrade pip && \
	pip install -r requirements.txt

install: venv

fix:
	# isot and black
	@. .venv/bin/activate; \
	isort . && \
	black .


serve: fix
	@echo "Starting HTTP server at http://localhost:7070"
	@. .venv/bin/activate; \
	. .env && \
	PYTHONPATH=. python -m server
	
