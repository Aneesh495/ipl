.PHONY: setup refresh ingest train site assets all test serve

PYTHON := .venv/bin/python

setup:
	uv sync --python 3.13

refresh:
	$(PYTHON) scripts/refresh_data.py

ingest:
	$(PYTHON) scripts/build_database.py

train: ingest
	OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=2 $(PYTHON) scripts/train_models.py

site: train
	$(PYTHON) scripts/build_site_data.py
	$(PYTHON) scripts/fingerprint_site.py

assets:
	$(PYTHON) scripts/fingerprint_site.py

all: site

test:
	$(PYTHON) scripts/fingerprint_site.py --check
	$(PYTHON) -m unittest discover -s tests -v
	node tests/site_smoke.cjs

serve:
	$(PYTHON) -m http.server 8000
