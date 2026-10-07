#!/bin/sh
set -eu

pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput

if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_EMAIL:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    python manage.py shell -c "import os; from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.filter(username=os.environ['DJANGO_SUPERUSER_USERNAME']).exists() or User.objects.create_superuser(os.environ['DJANGO_SUPERUSER_USERNAME'], os.environ['DJANGO_SUPERUSER_EMAIL'], os.environ['DJANGO_SUPERUSER_PASSWORD'])"
fi

if [ "${SEED_DEMO_DATA:-False}" = "true" ] || [ "${SEED_DEMO_DATA:-False}" = "True" ]; then
    python manage.py seed_demo_data
fi
