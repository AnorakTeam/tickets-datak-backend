#!/bin/sh
set -e

# If a custom command was provided (e.g. docker run ... python manage.py test), execute it directly
if [ "$#" -gt 0 ] && [ "$1" != "gunicorn" ]; then
    exec "$@"
fi

PORT="${PORT:-8080}"
echo "==> Starting tickets-datak-backend on port ${PORT}..."

# Wait/Run database migrations
echo "==> Running database migrations..."
python manage.py migrate --noinput

# Ensure Django DatabaseCache table exists for shared chatbot sessions
echo "==> Ensuring cache table exists..."
python manage.py createcachetable || true

# Seed default test/demo data (idempotent)
if [ "${AUTO_SEED:-True}" = "True" ] || [ "${AUTO_SEED:-true}" = "true" ]; then
    echo "==> Running seed_data..."
    python manage.py seed_data || true
fi

# Collect static files for WhiteNoise
echo "==> Collecting static files..."
python manage.py collectstatic --noinput --clear || true

echo "==> Starting Gunicorn server..."
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --access-logfile - \
    --error-logfile -
