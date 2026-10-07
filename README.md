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

