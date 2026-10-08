# Render deployment

The current Blueprint uses Render's Free web-service and PostgreSQL plans. Free web services can sleep when idle, and Free PostgreSQL databases expire 30 days after creation. Upgrade the database to a paid plan before its expiry if you need to preserve deployment data; keep a backup before changing plans.

1. Commit these files, push the branch, and merge it into `main`.
2. In Render, choose **New → Blueprint**, connect the repository, and approve `render.yaml`.
3. Render creates PostgreSQL and injects `DATABASE_URL`; it also generates `SECRET_KEY` and sets `DEBUG=False`.
4. In the web service environment page, set `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, and `DJANGO_SUPERUSER_PASSWORD` before the first deploy. Also set every `EMAIL_*` variable required by your SMTP or email API integration.
5. Deploy. The generated administrator can log in at `/accounts/login/`; the live URL appears on the service overview.

Redeploy from the Render dashboard or by pushing to `main`. Set `SEED_DEMO_DATA=True` for one deployment only if demo records are wanted.

## Troubleshooting

- **Build failed:** inspect the build log; verify all administrator values are set or leave all three unset.
- **400 Bad Request:** Render supplies `RENDER_EXTERNAL_HOSTNAME`; if using a custom domain, add it to `ALLOWED_HOSTS` and its `https://` origin to `CSRF_TRUSTED_ORIGINS`.
- **Static files missing:** ensure the build completed `collectstatic`; WhiteNoise serves `STATIC_ROOT`.
- **CSRF login error:** confirm the site is HTTPS and the trusted origin matches exactly.
- **Database connection error:** confirm the Render database is linked and `DATABASE_URL` comes from it.
- **Email not sending:** check Render logs. Some SMTP providers block connections; use an email API provider that offers SMTP credentials or adapt the email backend through environment variables.
- **Slow first request:** free services sleep after inactivity.

The application currently persists its business data in PostgreSQL. CSV uploads are processed in memory rather than stored. Any future local-disk media on Render is ephemeral and needs object storage for persistence.
