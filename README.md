live url - https://exam-duty-manager.onrender.com/


# ExamDutyManager

ExamDutyManager is a Django web application to automatically allocate exam invigilation duties with constraints, manage seating plans, and track UFM (Unfair Means) records.

## Features

- Admin-only login (Django auth, staff users only)
- Manage Faculty, PhD Scholars, Classrooms, Exam Schedules, UFM Records
- Automatic duty allocation with:
  - 1 Professor, 2 Assistant Professors, 3 PhD Scholars per room
  - No overlapping duties
  - One-slot-per-day gap for Professors and PhD Scholars
  - Fair, random weighted distribution using previous duties and UFM counts
  - Validation error if staff are insufficient
- Allocation table:
  - Search, filter by date and slot
  - Pagination
  - Export to CSV
  - Download duty order as PDF
- Email notifications to faculty for their allocations (console backend by default)
- Seating plan page based on classroom capacity with roll number ranges
- UFM history page
- Modern Bootstrap 5 dashboard UI with sidebar and Chart.js duty distribution graph

## Setup

```bash
cd Mini_Project
python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt

python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser  # create admin (must be staff)
python manage.py runserver
```

Then open `http://127.0.0.1:8000/` and log in with the superuser to access the dashboard.

## New administration workflows

- **Availability:** Faculty and PhD accounts use *My Availability*; administrators can review the whole availability list. Weekly timetable conflicts and date-specific unavailable periods are excluded from duty selection.
- **Individual access:** Create a faculty or scholar with the temporary-login option, or link a Django user to a profile in Django Admin. Imported profiles can receive password setup links by email. Users can reset forgotten passwords from the login page.
- **Duty replacement:** The assigned person sends a request from their dashboard. Eligible recipients accept or reject it. Acceptance updates the current duty immediately and preserves the request record; administrators receive an in-app notification.
- **Session seating:** Create an exam session from the seating page, assign schedules to it in the exam schedule form, then generate one shared seating plan. The generated plan has CSV and PDF exports. Seat tables and exports contain roll numbers rather than names.
- **Official duty charts:** Each schedule has a Mid Semester / End Semester type. The allocation page previews or downloads a compact MANIT-style chart for either type, with date-wise and shift-wise filters, repeated headings, one room row containing all assigned faculty/designations and PhD scholar IDs, editable notes, and coordinator/HOD signature space. Individual faculty duty details list all current assignments; individual faculty and PhD duty slips remain available. Accepted replacements appear from the live duty allocation record.
- Configure `INSTITUTE_NAME`, `EXAM_DUTY_DEPARTMENT`, `EXAM_DUTY_REFERENCE`, and `EXAM_DUTY_DEFAULT_NOTE` in the environment for official heading, reference, and fallback note. Per-exam instructions/notes and the examination type are editable in the exam schedule form. Older schedules are marked End Semester by the migration default and can be reclassified in the schedule editor. The allocation data has no cancellation status; remove a cancelled duty from the active allocation to keep it out of the issued chart.
- **Bulk import:** Administrators can open **Bulk Import**, download CSV templates, upload CSV/XLSX files, inspect row validation, and import valid rows. Student category supports regular, minor, and elective; student subject registrations can be supplied in a semicolon-separated `subjects` column.

Production deployments must set `DEBUG=False`, a strong `SECRET_KEY`, persistent PostgreSQL `DATABASE_URL`, and appropriate `ALLOWED_HOSTS`, email, and HTTPS settings. CSV and XLSX imports use the Python standard library when `openpyxl` is not installed; installing `openpyxl` enables richer XLSX cell decoding.

Email delivery uses Django's console backend by default, so local runs print email contents to the server console while still recording delivery history. For SMTP, set `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, and `DEFAULT_FROM_EMAIL` in the process/deployment environment. For Gmail, use `smtp.gmail.com`, port `587`, TLS enabled, and a provider app password. The outbox records attempts and errors; staff can search delivery history and retry failed messages from **Email delivery**.

