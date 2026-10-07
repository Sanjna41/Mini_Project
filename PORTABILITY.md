# Portable setup

Supported Python versions: 3.10, 3.11, and 3.12. Python 3.12 is the default in `.python-version` and Docker.

Local development defaults to SQLite and console email; no environment configuration is required.

## Windows

Run `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`, then `scripts/run.ps1`.

## Linux and macOS

Run `make setup`, then `make run`. If `python3.12` is installed under a different command, use `make PYTHON=python3.12 setup`.

## Environment variables

Copy `.env.example` as a reference and configure environment variables in your shell or host dashboard. `DATABASE_URL` selects PostgreSQL; leave it unset for SQLite. Other settings are `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `TIME_ZONE`, `STATIC_ROOT`, `MEDIA_ROOT`, `LOG_PATH`, and all `EMAIL_*` variables listed in `.env.example`.

Use a PostgreSQL URL such as `postgresql://user:password@host:5432/database`. For production set `DEBUG=False` and a strong `SECRET_KEY`.

## Docker

Copy `.env.example` to `.env`, set a non-placeholder `SECRET_KEY`, then run `docker compose up --build`. The app listens at `http://localhost:8000/health` and uses PostgreSQL.

## Troubleshooting

- **Port in use:** run Django on another port: `python manage.py runserver 8001`.
- **Migration error:** confirm the intended `DATABASE_URL`, then run `python manage.py migrate`.
- **Email error:** use console email locally; SMTP providers commonly need TLS and an app password.
- **Static files missing:** run `python manage.py collectstatic --noinput` and verify `STATIC_ROOT` is writable.
- **CSV encoding error:** save the spreadsheet as UTF-8 CSV; CSV readers use `utf-8-sig` for Excel's BOM.

Media is configurable, but the app currently stores no model uploads on disk; CSV files are processed in memory. If future uploads are saved to local disk on Render, they will be lost on redeploy and should move to object storage.
