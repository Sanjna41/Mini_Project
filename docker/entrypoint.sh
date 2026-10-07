#!/bin/sh
set -eu

attempt=0
until python manage.py migrate --noinput; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        echo "Database did not become available." >&2
        exit 1
    fi
    sleep 2
done

python manage.py collectstatic --noinput
exec gunicorn ExamDutyManager.wsgi:application --bind 0.0.0.0:8000
