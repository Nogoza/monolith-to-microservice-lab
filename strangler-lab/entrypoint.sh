#!/bin/sh
set -e

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting gunicorn..."
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --worker-class gthread \
    --workers 1 \
    --threads 4 \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
