.PHONY: setup ingest visuals model all clean

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

ingest:
	.venv/bin/python import_ipl_data.py

visuals:
	.venv/bin/python ipl_visuals.py

model:
	.venv/bin/python ipl_modeling.py

all: ingest visuals model

clean:
	rm -rf .venv __pycache__ *.pyc
