PYTHON ?= python3

setup:
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt && python manage.py migrate && python manage.py seed_demo_data

run:
	. .venv/bin/activate && python manage.py runserver

test:
	. .venv/bin/activate && python manage.py test
