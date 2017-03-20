all: lint test

test:
	python goldtest/test_goldtest.py

lint:
	flake8 .

.PHONY: test lint
