SHELL := /bin/bash

OS := $(shell uname -s)

DEVICE=cpu

default: serve

create-env:
	@test -f .env || (echo "Creating .env file with empty variables" && touch .env && \
	echo "export S3_BUCKET=\n" >> .env \
	echo "export XAI_API_KEY=\n" >> .env \
	echo "export USERNAME=\n" >> .env \
	echo "export PASSWORD=\n" >> .env \
	echo "export AWS_ACCESS_KEY_ID=\n" >> .env \
	echo "export AWS_SECRET_ACCESS_KEY=\n" >> .env \
	echo "export AWS_REGION=\n" >> .env)

venv:
	@test -d .venv || python3.12 -m venv .venv
	@. .venv/bin/activate && \
	pip install --upgrade pip && \
	pip install -r requirements.txt

install: venv create-env

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
