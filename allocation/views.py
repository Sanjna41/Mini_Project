from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.http import require_POST
import csv
import uuid
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from .allocation_algorithm import allocate_all_duties
from .csv_merge import merge_seating_csv
from .seating_allocator import (
    InsufficientCapacityError, RoomInput, StudentInput, allocate_seats,
    contiguous_ranges,
)
from .decorators import staff_required
from .forms import (
    ClassroomForm,
    ExamScheduleForm,
    FacultyForm,
    PhDScholarForm,
    UFMRecordForm,
    AvailabilityForm, ReplacementRequestForm, ExamSessionForm, AnnouncementForm, SubjectForm,
)
from .models import (
    Classroom,
    DutyAllocation,
    ExamSchedule,
    Faculty,
    PhDScholar,
    UFMRecord,
    ExamSection,
    Seating,
    SeatingAllotment,
    Student,
    Section,
    Availability, TimetableEntry, ReplacementRequest, Notification,
    ExamSession, SessionSeating, SessionSeatingAllotment, StudentSubjectRegistration, ImportBatch, Subject, EmailNotification,
)
from .imports import IMPORT_SCHEMAS, read_tabular_upload, validate_import_rows
from .email_notifications import (
    duty_email_details, queue_admin_email, queue_person_email, send_queued_email,
)
from .duty_order_pdf import (
    allocation_queryset, build_duty_chart, build_faculty_details, build_individual_slip,
)


@login_required
def dashboard(request):
    if not request.user.is_staff:
        return redirect('allocation:my_dashboard')
    context = {
        'faculty_count': Faculty.objects.count(),
        'phd_count': PhDScholar.objects.count(),
        'classroom_count': Classroom.objects.count(),
        'exam_count': ExamSchedule.objects.count(),
        'session_count': ExamSession.objects.count(),
        'allocation_count': DutyAllocation.objects.count(),
        'ufm_count': UFMRecord.objects.count(),
        'pending_replacements': ReplacementRequest.objects.filter(status=ReplacementRequest.Status.PENDING).count(),
        'recent_replacements': ReplacementRequest.objects.filter(status=ReplacementRequest.Status.ACCEPTED).select_related('allocation__exam_schedule', 'allocation__classroom').order_by('-resolved_at')[:8],
        'unavailable_count': Availability.objects.filter(is_available=False).values('faculty_id', 'phd_scholar_id').distinct().count(),
        'notifications': request.user.exam_notifications.order_by('-created_at')[:8],
        'email_failed_count': EmailNotification.objects.filter(status=EmailNotification.Status.FAILED).count(),
        'missing_email_count': Faculty.objects.filter(email='').count() + PhDScholar.objects.filter(email='').count(),
        'coordinator_issue_count': ExamSchedule.objects.filter(subject__isnull=False).exclude(
            coordinator_status=ExamSchedule.CoordinatorStatus.ASSIGNED).count(),
    }

    duty_counts = (
        Faculty.objects.annotate(duty_total=Count('duty_allocations')).order_by('name')
    )
    context['chart_labels'] = [f.name for f in duty_counts]
    context['chart_data'] = [f.duty_total for f in duty_counts]

    return render(request, 'allocation/dashboard.html', context)


def _current_person(user):
    faculty = getattr(user, 'faculty_profile', None)
    phd = getattr(user, 'phd_profile', None)
    return faculty, phd


@login_required
def my_dashboard(request):
    faculty, phd = _current_person(request.user)
    if not (faculty or phd):
        return redirect('allocation:dashboard')
    if (faculty and faculty.must_change_password) or (phd and phd.must_change_password):
        return redirect('allocation:password_change')
    duties = DutyAllocation.objects.filter(faculty=faculty) if faculty else DutyAllocation.objects.filter(phd_scholar=phd)
    context = {
        'person': faculty or phd,
        'duties': duties.select_related('exam_schedule', 'classroom').order_by('exam_schedule__date'),
        'availability': Availability.objects.filter(faculty=faculty) if faculty else Availability.objects.filter(phd_scholar=phd),
        'notifications': request.user.exam_notifications.order_by('-created_at')[:30],
        'requests': ReplacementRequest.objects.filter(requested_by=request.user).select_related('allocation__exam_schedule'),
        'incoming': ReplacementRequest.objects.filter(status=ReplacementRequest.Status.PENDING,
            target_faculty=faculty) if faculty else ReplacementRequest.objects.filter(status=ReplacementRequest.Status.PENDING, target_phd_scholar=phd),
        'faculty_options': Faculty.objects.exclude(pk=getattr(faculty, 'pk', None)).order_by('name'),
        'phd_options': PhDScholar.objects.exclude(pk=getattr(phd, 'pk', None)).order_by('name'),
        'timetable': TimetableEntry.objects.filter(faculty=faculty) if faculty else TimetableEntry.objects.filter(phd_scholar=phd),
    }
    return render(request, 'allocation/person_dashboard.html', context)


@login_required
def availability_manage(request):
    faculty, phd = _current_person(request.user)
    if not (faculty or phd):
        if request.user.is_staff:
            return redirect('allocation:availability_admin')
        return redirect('allocation:dashboard')
    if request.method == 'POST':
        form = AvailabilityForm(request.POST)
        form.instance.faculty, form.instance.phd_scholar = faculty, phd
        if form.is_valid():
            item = form.save(commit=False)
            item.save()
            messages.success(request, 'Availability saved.')
            return redirect('allocation:availability')
    else:
        form = AvailabilityForm()
    records = Availability.objects.filter(faculty=faculty) if faculty else Availability.objects.filter(phd_scholar=phd)
    return render(request, 'allocation/availability.html', {'form': form, 'records': records.order_by('-date')})


@staff_required
def availability_admin(request):
    entries = Availability.objects.select_related('faculty', 'phd_scholar').order_by('date', 'start_time')
    return render(request, 'allocation/availability_admin.html', {'records': entries})


@staff_required
def announcement_create(request):
    if request.method == 'POST':
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            from django.contrib.auth import get_user_model
            user_ids = get_user_model().objects.filter(
                Q(faculty_profile__isnull=False) | Q(phd_profile__isnull=False) | Q(is_staff=True)
            ).values_list('pk', flat=True).distinct()
            Notification.objects.bulk_create([
                Notification(recipient_id=user_id, message='Admin announcement: ' + form.cleaned_data['message'])
                for user_id in user_ids
            ])
            event_key = uuid.uuid4().hex
            text = form.cleaned_data['message']
            for person in list(form.cleaned_data['faculty']) + list(form.cleaned_data['phd_scholars']):
                queue_person_email(person,
                    notification_type='ANNOUNCEMENT', template_key='announcement',
                    subject='Examination office announcement',
                    details=[('Announcement', text)],
                    idempotency_key=f'announcement:{event_key}:{person._meta.label_lower}:{person.pk}',
                    intro='The examination office has sent you an important announcement.')
            messages.success(request, f'Announcement sent to {len(user_ids)} accounts and queued for the selected email recipients.')
            return redirect('allocation:dashboard')
    else:
        form = AnnouncementForm()
    return render(request, 'allocation/announcement_form.html', {'form': form})


@staff_required
def email_management(request):
    emails = EmailNotification.objects.select_related('recipient').all()
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    kind = request.GET.get('type', '').strip()
    date_filter = request.GET.get('date', '').strip()
    if query:
        emails = emails.filter(Q(recipient_email__icontains=query) | Q(recipient_name__icontains=query) | Q(subject__icontains=query))
    if status in EmailNotification.Status.values:
        emails = emails.filter(status=status)
    if kind in EmailNotification.Type.values:
        emails = emails.filter(notification_type=kind)
    parsed_date = parse_date(date_filter) if date_filter else None
    if parsed_date:
        emails = emails.filter(created_at__date=parsed_date)
    page = Paginator(emails, 30).get_page(request.GET.get('page'))
    return render(request, 'allocation/email_management.html', {
        'page': page, 'query': query, 'status_filter': status, 'type_filter': kind,
        'date_filter': date_filter, 'statuses': EmailNotification.Status.choices,
        'types': EmailNotification.Type.choices,
        'counts': {value: EmailNotification.objects.filter(status=value).count() for value, _ in EmailNotification.Status.choices},
    })


@staff_required
@require_POST
def email_retry(request, notification_id):
    item = get_object_or_404(EmailNotification, pk=notification_id)
    stale_processing = (item.status == EmailNotification.Status.PROCESSING and item.last_attempt_at and
        item.last_attempt_at < timezone.now() - timezone.timedelta(minutes=5))
    if item.status not in (EmailNotification.Status.FAILED, EmailNotification.Status.PENDING) and not stale_processing:
        messages.warning(request, 'Only failed or pending emails can be retried.')
    else:
        sent = send_queued_email(item.pk)
        if sent:
            messages.success(request, 'Email delivery succeeded.')
        else:
            messages.error(request, 'Email delivery failed again. Review the recorded error and email configuration.')
    return redirect('allocation:email_management')


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _replacement_eligible(faculty, phd, allocation):
    exam = allocation.exam_schedule
    if allocation.is_subject_coordinator:
        if not faculty or not exam.subject_id or exam.subject.coordinator_id != faculty.pk:
            return False, 'This coordinator duty can only be covered by the faculty coordinator configured for this subject.'
    if faculty:
        if allocation.role_type == DutyAllocation.RoleType.PHD_SCHOLAR:
            return False, 'This duty requires a PhD scholar.'
        if allocation.role_type == DutyAllocation.RoleType.PROFESSOR and faculty.designation == Faculty.Designation.ASSISTANT_PROFESSOR:
            return False, 'This duty requires a Professor or Associate Professor.'
        if allocation.role_type == DutyAllocation.RoleType.ASSISTANT_PROFESSOR and faculty.designation != Faculty.Designation.ASSISTANT_PROFESSOR:
            return False, 'This duty requires an Assistant Professor.'
        if faculty.duty_allocations.filter(exam_schedule__date=exam.date).exists():
            return False, 'The replacement already has a duty that day.'
        timetable = TimetableEntry.objects.filter(faculty=faculty, weekday=exam.date.weekday())
        availability = Availability.objects.filter(faculty=faculty, date=exam.date, is_available=False)
        duties = DutyAllocation.objects.filter(faculty=faculty, exam_schedule__date=exam.date).select_related('exam_schedule')
    else:
        if allocation.role_type != DutyAllocation.RoleType.PHD_SCHOLAR:
            return False, 'This duty requires a faculty member.'
        if phd.duty_allocations.filter(exam_schedule__date=exam.date).exists():
            return False, 'The replacement already has a duty that day.'
        timetable = TimetableEntry.objects.filter(phd_scholar=phd, weekday=exam.date.weekday())
        availability = Availability.objects.filter(phd_scholar=phd, date=exam.date, is_available=False)
        duties = DutyAllocation.objects.filter(phd_scholar=phd, exam_schedule__date=exam.date).select_related('exam_schedule')
    if any(_overlaps(exam.start_time, exam.end_time, t.start_time, t.end_time) for t in timetable):
        return False, 'The replacement has a timetable conflict.'
    if any(_overlaps(exam.start_time, exam.end_time, a.start_time, a.end_time) for a in availability):
        return False, 'The replacement marked this time unavailable.'
    if any(_overlaps(exam.start_time, exam.end_time, d.exam_schedule.start_time, d.exam_schedule.end_time) for d in duties):
        return False, 'The replacement has an overlapping duty.'
    person = faculty or phd
    if person.duty_allocations.count() >= person.duty_quota:
        return False, 'The replacement has reached their duty quota.'
    return True, ''


def create_personal_account(person, profile):
    """Create a one-time credential for a profile with an email address."""
    from django.contrib.auth import get_user_model
    from django.utils.crypto import get_random_string
    User = get_user_model()
    if not profile.email:
        return None
    username = profile.employee_id if isinstance(profile, Faculty) else profile.scholar_id
    username = (username or profile.email).strip()
    if User.objects.filter(username=username).exists() or User.objects.filter(email=profile.email).exists():
        raise ValidationError('An account already uses this username or email.')
    password = get_random_string(18)
    user = User.objects.create_user(username=username, email=profile.email, password=password, first_name=profile.name)
    person.user = user
    person.must_change_password = True
    person.save(update_fields=['user', 'must_change_password'])
    return username, password


class ProfilePasswordChangeView(PasswordChangeView):
    template_name = 'allocation/change_password.html'
    success_url = reverse_lazy('allocation:my_dashboard')

    def form_valid(self, form):
        faculty, phd = _current_person(self.request.user)
        if faculty:
            faculty.must_change_password = False
            faculty.save(update_fields=['must_change_password'])
        if phd:
            phd.must_change_password = False
            phd.save(update_fields=['must_change_password'])
        return super().form_valid(form)


@staff_required
def data_import(request, batch_id=None):
    batch = get_object_or_404(ImportBatch, pk=batch_id, created_by=request.user) if batch_id else None
    if request.method == 'POST' and not batch:
        import_type = request.POST.get('import_type', '')
        upload = request.FILES.get('data_file')
        try:
            if import_type not in IMPORT_SCHEMAS or not upload:
                raise ValueError('Choose a data type and a CSV or XLSX file.')
            parsed = read_tabular_upload(upload)
            preview = validate_import_rows(import_type, parsed)
            batch = ImportBatch.objects.create(import_type=import_type, filename=upload.name,
                rows=preview, created_by=request.user)
            messages.success(request, 'Preview ready. Review row errors before importing valid rows.')
            return redirect('allocation:data_import_batch', batch_id=batch.pk)
        except (ValueError, UnicodeDecodeError, Exception) as exc:
            # XLSX parser errors and malformed CSVs are reported without exposing a traceback.
            messages.error(request, str(exc))
    elif request.method == 'POST' and batch:
        if batch.imported_at:
            messages.error(request, 'This import has already been processed.')
            return redirect('allocation:data_import')
        good = [row for row in batch.rows if not row['errors']]
        imported, failed = 0, []
        with transaction.atomic():
            for row in good:
                data = row['data']
                try:
                    with transaction.atomic():
                        _import_one(batch.import_type, data)
                        if request.POST.get('create_accounts') and batch.import_type in ('faculty', 'phd'):
                            _create_import_account(batch.import_type, data, request)
                    imported += 1
                except Exception as exc:
                    failed.append({'line': row['line'], 'errors': [str(exc)]})
            batch.imported_at = timezone.now()
            batch.report = {'imported': imported, 'invalid': len(batch.rows) - len(good), 'failed': failed}
            batch.save(update_fields=['imported_at', 'report'])
        messages.success(request, f'Imported {imported} rows; {len(batch.rows) - len(good) + len(failed)} rows need attention.')
        return redirect('allocation:data_import_batch', batch_id=batch.pk)
    history = ImportBatch.objects.filter(created_by=request.user).order_by('-created_at')[:25]
    return render(request, 'allocation/data_import.html', {'schemas': IMPORT_SCHEMAS, 'batch': batch, 'history': history})


def _import_one(import_type, row):
    if import_type == 'subjects':
        subject, _ = Subject.objects.get_or_create(name=row['name'])
        identifier = row.get('coordinator_email', '').strip()
        employee_id = row.get('coordinator_employee_id', '').strip()
        if identifier or employee_id:
            matches = Faculty.objects.all()
            by_email = Faculty.objects.filter(email__iexact=identifier) if identifier else None
            by_id = Faculty.objects.filter(employee_id__iexact=employee_id) if employee_id else None
            if by_email is not None and by_email.count() != 1:
                raise ValueError('Coordinator email must match exactly one existing faculty member.')
            if by_id is not None and by_id.count() != 1:
                raise ValueError('Coordinator employee ID must match exactly one existing faculty member.')
            faculty = (by_email.first() if by_email is not None else by_id.first())
            if by_email is not None and by_id is not None and by_email.first().pk != by_id.first().pk:
                raise ValueError('Coordinator email and employee ID refer to different faculty members.')
            subject.coordinator = faculty
            subject.save(update_fields=['coordinator'])
            ExamSchedule.objects.filter(subject=subject).update(
                coordinator_status=ExamSchedule.CoordinatorStatus.PENDING,
                coordinator_note='Coordinator imported; rerun duty allocation to verify and assign.',
            )
    elif import_type == 'sections':
        Section.objects.update_or_create(name=row['name'], defaults={'department': row.get('department', '')})
    elif import_type == 'classrooms':
        Classroom.objects.update_or_create(name=row['name'], defaults={'rows': row['rows'], 'columns': row['columns']})
    elif import_type == 'faculty':
        lookup = {'employee_id': row['employee_id']} if row.get('employee_id') else {'email': row['email']}
        defaults = {'name': row['name'], 'email': row['email'], 'designation': row['designation'],
            'duty_quota': int(row.get('duty_quota') or 10), 'department': row.get('department', ''),
            'contact': row.get('contact', ''), 'employee_id': row.get('employee_id') or None}
        Faculty.objects.update_or_create(**lookup, defaults=defaults)
    elif import_type == 'phd':
        lookup = {'scholar_id': row['scholar_id']} if row.get('scholar_id') else {'email': row['email']}
        defaults = {'name': row['name'], 'email': row['email'], 'duty_quota': int(row.get('duty_quota') or 12),
            'department': row.get('department', ''), 'academic_year': row.get('academic_year', ''),
            'contact': row.get('contact', ''), 'scholar_id': row.get('scholar_id') or None}
        PhDScholar.objects.update_or_create(**lookup, defaults=defaults)
    elif import_type == 'students':
        section, _ = Section.objects.get_or_create(name=row['section'])
        student, _ = Student.objects.update_or_create(section=section, roll_no=row['roll_no'], defaults={'name': row.get('name', ''), 'category': row['category']})
        for subject_name in filter(None, (value.strip() for value in row.get('subjects', '').split(';'))):
            subject, _ = Subject.objects.get_or_create(name=subject_name)
            category = 'MINOR' if student.category == Student.Category.MINOR else 'ELECTIVE'
            StudentSubjectRegistration.objects.update_or_create(student=student, subject=subject, defaults={'category': category})
    elif import_type in ('faculty_timetable', 'phd_timetable'):
        is_faculty = import_type == 'faculty_timetable'
        profile = (Faculty.objects.get(employee_id=row['employee_id']) if is_faculty else PhDScholar.objects.get(scholar_id=row['scholar_id']))
        defaults = {'weekday': row['weekday'], 'start_time': row['start_time'], 'end_time': row['end_time'], 'label': row.get('label', '')}
        lookup = {'faculty': profile} if is_faculty else {'phd_scholar': profile}
        if not TimetableEntry.objects.filter(**lookup, **defaults).exists():
            TimetableEntry.objects.create(**lookup, **defaults)
    elif import_type in ('minor_registrations', 'elective_registrations'):
        section = Section.objects.get(name=row['section'])
        student = Student.objects.get(section=section, roll_no=row['roll_no'])
        subject, _ = Subject.objects.get_or_create(name=row['subject'])
        category = 'MINOR' if import_type == 'minor_registrations' else 'ELECTIVE'
        student.category = category
        student.save(update_fields=['category'])
        StudentSubjectRegistration.objects.update_or_create(student=student, subject=subject, defaults={'category': category})


def _create_import_account(import_type, row, request):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.forms import PasswordResetForm
    from django.utils.crypto import get_random_string
    User = get_user_model()
    if import_type == 'faculty':
        profile = Faculty.objects.get(employee_id=row['employee_id']) if row.get('employee_id') else Faculty.objects.get(email=row['email'])
        username = profile.employee_id or profile.email
    else:
        profile = PhDScholar.objects.get(scholar_id=row['scholar_id']) if row.get('scholar_id') else PhDScholar.objects.get(email=row['email'])
        username = profile.scholar_id or profile.email
    if profile.user_id:
        return
    if User.objects.filter(email=profile.email).exists():
        raise ValidationError('An account already uses this email. Link the existing account from the admin profile.')
    user = User(username=username, email=profile.email, first_name=profile.name)
    user.set_password(get_random_string(64))
    user.save()
    profile.user = user
    profile.save(update_fields=['user'])
    PasswordResetForm({'email': profile.email}).save(
        request=request, use_https=request.is_secure(), domain_override=request.get_host(),
        subject_template_name='registration/password_reset_subject.txt',
        email_template_name='registration/password_reset_email.html',
    )


@login_required
@require_POST
def replacement_request(request, allocation_id):
    faculty, phd = _current_person(request.user)
    allocation = get_object_or_404(DutyAllocation, pk=allocation_id)
    if allocation.faculty_id != getattr(faculty, 'pk', None) and allocation.phd_scholar_id != getattr(phd, 'pk', None):
        return HttpResponse('Not permitted', status=403)
    if allocation.replacement_requests.filter(status=ReplacementRequest.Status.PENDING).exists():
        messages.error(request, 'A replacement request is already pending for this duty.')
        return redirect('allocation:my_dashboard')
    form = ReplacementRequestForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.allocation, item.requested_by = allocation, request.user
        item.replaced_faculty, item.replaced_phd_scholar = faculty, phd
        target = item.target_faculty or item.target_phd_scholar
        valid, reason = _replacement_eligible(item.target_faculty, item.target_phd_scholar, allocation)
        if valid and (target.user_id != request.user.id):
            item.save()
            if target.user_id:
                Notification.objects.create(recipient_id=target.user_id, message=f'Replacement request for {allocation.exam_schedule} in room {allocation.classroom.name}.')
            details = [('Original person', str(faculty or phd))] + duty_email_details(allocation)
            queue_person_email(target,
                notification_type='REPLACEMENT_REQUEST', template_key='replacement_request',
                subject=f'Duty replacement request · {allocation.exam_schedule.date:%d %b %Y}',
                details=details, idempotency_key=f'replacement-request:{item.pk}:target',
                intro=f'{faculty or phd} has asked you to take this examination duty.')
            messages.success(request, 'Replacement request sent.')
        else:
            messages.error(request, reason or 'You cannot request yourself as a replacement.')
    else:
        messages.error(request, 'Choose one eligible replacement person.')
    return redirect('allocation:my_dashboard')


@login_required
@require_POST
@transaction.atomic
def replacement_respond(request, request_id, action):
    item = get_object_or_404(ReplacementRequest.objects.select_for_update(), pk=request_id, status=ReplacementRequest.Status.PENDING)
    faculty, phd = _current_person(request.user)
    is_target = item.target_faculty_id == getattr(faculty, 'pk', None) and faculty or item.target_phd_scholar_id == getattr(phd, 'pk', None) and phd
    if not is_target or action not in ('accept', 'reject'):
        return HttpResponse('Not permitted', status=403)
    allocation = DutyAllocation.objects.select_for_update().select_related('exam_schedule', 'classroom').get(pk=item.allocation_id)
    if allocation.faculty_id != item.replaced_faculty_id or allocation.phd_scholar_id != item.replaced_phd_scholar_id:
        return HttpResponse('This duty has already changed. The request is no longer valid.', status=409)
    if action == 'accept':
        eligible, reason = _replacement_eligible(faculty, phd, allocation)
        if not eligible:
            messages.error(request, reason)
            return redirect('allocation:my_dashboard')
        replaced_person = item.replaced_faculty or item.replaced_phd_scholar
        replacement_person = faculty or phd
        allocation.faculty, allocation.phd_scholar = faculty, phd
        allocation.save(update_fields=['faculty', 'phd_scholar'])
        if allocation.is_subject_coordinator:
            schedule = allocation.exam_schedule
            schedule.coordinator_status = (
                ExamSchedule.CoordinatorStatus.ASSIGNED
                if schedule.subject_id and schedule.subject.coordinator_id == faculty.pk
                else ExamSchedule.CoordinatorStatus.UNRESOLVED
            )
            schedule.coordinator_note = '' if schedule.coordinator_status == ExamSchedule.CoordinatorStatus.ASSIGNED else 'Coordinator duty replacement does not match the configured subject coordinator.'
            schedule.save(update_fields=['coordinator_status', 'coordinator_note'])
        item.status = ReplacementRequest.Status.ACCEPTED
        detail = (f"Duty replacement successful: {item.replaced_faculty or item.replaced_phd_scholar} replaced by {faculty or phd}; "
                  f"{allocation.exam_schedule.date} {allocation.exam_schedule.start_time}-{allocation.exam_schedule.end_time}, "
                  f"room {allocation.classroom.name}, {allocation.get_role_type_display()}.")
        for admin in __import__('django.contrib.auth.models', fromlist=['User']).User.objects.filter(is_staff=True):
            Notification.objects.create(recipient=admin, message=detail)
        if item.requested_by_id:
            Notification.objects.create(recipient_id=item.requested_by_id, message=detail)
        if (faculty or phd).user_id:
            Notification.objects.create(recipient_id=(faculty or phd).user_id, message='You accepted a duty replacement request. ' + detail)
        replacement_details = [
            ('Original person', str(replaced_person)),
            ('Replacement person', str(replacement_person)),
        ] + duty_email_details(allocation)
        for person, recipient_tag in ((replaced_person, 'original'), (replacement_person, 'replacement')):
            queue_person_email(person,
                notification_type='REPLACEMENT_CONFIRMATION', template_key='replacement_confirmation',
                subject=f'Duty replacement confirmed · {allocation.exam_schedule.date:%d %b %Y}',
                details=replacement_details, idempotency_key=f'replacement-accepted:{item.pk}:{recipient_tag}',
                intro='The replacement was accepted. The duty allocation has been updated.')
        queue_admin_email(subject=f'Duty replacement completed · {allocation.exam_schedule.date:%d %b %Y}',
            notification_type='REPLACEMENT_CONFIRMATION', template_key='replacement_confirmation',
            details=replacement_details, idempotency_prefix=f'replacement-accepted:{item.pk}',
            intro='A duty replacement was accepted and applied automatically.')
        messages.success(request, 'Duty replacement completed. Administrators have been notified.')
    else:
        item.status = ReplacementRequest.Status.REJECTED
        Notification.objects.create(recipient_id=item.requested_by_id, message='Your duty replacement request was rejected.')
        requester = item.replaced_faculty or item.replaced_phd_scholar
        if requester:
            queue_person_email(requester,
                notification_type='REPLACEMENT_REJECTION', template_key='replacement_rejection',
                subject=f'Duty replacement request declined · {item.allocation.exam_schedule.date:%d %b %Y}',
                details=[('Requested replacement', str(item.target_faculty or item.target_phd_scholar))] + duty_email_details(item.allocation),
                idempotency_key=f'replacement-rejected:{item.pk}:requester',
                intro='The person you asked has declined the duty replacement request.')
        messages.info(request, 'Replacement request rejected.')
    item.resolved_at = timezone.now()
    item.save(update_fields=['status', 'resolved_at'])
    return redirect('allocation:my_dashboard')


@staff_required
def faculty_list(request):
    faculty = Faculty.objects.all().order_by('name')
    return render(request, 'allocation/faculty_list.html', {'faculty_list': faculty})


@staff_required
def subject_list(request):
    subjects = Subject.objects.select_related('coordinator').order_by('name')
    for subject in subjects:
        subject.schedules = list(ExamSchedule.objects.filter(subject=subject).order_by('date', 'slot'))
    return render(request, 'allocation/subject_list.html', {'subjects': subjects})


@staff_required
def subject_create(request, pk=None):
    subject = get_object_or_404(Subject, pk=pk) if pk else None
    form = SubjectForm(request.POST or None, instance=subject)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Subject coordinator saved. Rerun allocation to apply it to scheduled duties.')
        return redirect('allocation:subject_list')
    return render(request, 'allocation/subject_form.html', {'form': form, 'title': 'Edit Subject' if subject else 'Add Subject'})


@staff_required
def faculty_create(request):
    if request.method == 'POST':
        form = FacultyForm(request.POST)
        if form.is_valid():
            faculty = form.save()
            if request.POST.get('create_account'):
                try:
                    credentials = create_personal_account(faculty, faculty)
                    if credentials:
                        messages.warning(request, f'Temporary login — username: {credentials[0]}, password: {credentials[1]}. Provide these credentials securely; the user must change the password at first login.')
                except ValidationError as exc:
                    messages.error(request, str(exc))
            messages.success(request, 'Faculty added.')
            return redirect('allocation:faculty_list')
    else:
        form = FacultyForm()
    return render(
        request,
        'allocation/faculty_form.html',
        {'form': form, 'title': 'Add Faculty'},
    )


@staff_required
def faculty_edit(request, pk):
    faculty = get_object_or_404(Faculty, pk=pk)
    if request.method == 'POST':
        form = FacultyForm(request.POST, instance=faculty)
        if form.is_valid():
            form.save()
            messages.success(request, 'Faculty updated.')
            return redirect('allocation:faculty_list')
    else:
        form = FacultyForm(instance=faculty)
    return render(
        request,
        'allocation/faculty_form.html',
        {'form': form, 'title': 'Edit Faculty'},
    )


@staff_required
def phd_list(request):
    phds = PhDScholar.objects.all().order_by('name')
    return render(request, 'allocation/phd_list.html', {'phd_list': phds})


@staff_required
def phd_create(request):
    if request.method == 'POST':
        form = PhDScholarForm(request.POST)
        if form.is_valid():
            scholar = form.save()
            if request.POST.get('create_account'):
                try:
                    credentials = create_personal_account(scholar, scholar)
                    if credentials:
                        messages.warning(request, f'Temporary login — username: {credentials[0]}, password: {credentials[1]}. Provide these credentials securely; the user must change the password at first login.')
                except ValidationError as exc:
                    messages.error(request, str(exc))
            messages.success(request, 'PhD Scholar added.')
            return redirect('allocation:phd_list')
    else:
        form = PhDScholarForm()
    return render(
        request, 'allocation/phd_form.html', {'form': form, 'title': 'Add PhD Scholar'}
    )


@staff_required
def phd_edit(request, pk):
    phd = get_object_or_404(PhDScholar, pk=pk)
    if request.method == 'POST':
        form = PhDScholarForm(request.POST, instance=phd)
        if form.is_valid():
            form.save()
            messages.success(request, 'PhD Scholar updated.')
            return redirect('allocation:phd_list')
    else:
        form = PhDScholarForm(instance=phd)
    return render(
        request, 'allocation/phd_form.html', {'form': form, 'title': 'Edit PhD Scholar'}
    )


@staff_required
def classroom_list(request):
    rooms = Classroom.objects.all().order_by('name')
    return render(
        request, 'allocation/classroom_list.html', {'classroom_list': rooms}
    )


@staff_required
def classroom_create(request):
    if request.method == 'POST':
        form = ClassroomForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Classroom added.')
            return redirect('allocation:classroom_list')
    else:
        form = ClassroomForm()
    return render(
        request,
        'allocation/classroom_form.html',
        {'form': form, 'title': 'Add Classroom'},
    )


@staff_required
def classroom_edit(request, pk):
    room = get_object_or_404(Classroom, pk=pk)
    if request.method == 'POST':
        form = ClassroomForm(request.POST, instance=room)
        if form.is_valid():
            form.save()
            messages.success(request, 'Classroom updated.')
            return redirect('allocation:classroom_list')
    else:
        form = ClassroomForm(instance=room)
    return render(
        request,
        'allocation/classroom_form.html',
        {'form': form, 'title': 'Edit Classroom'},
    )


@staff_required
def exam_schedule_list(request):
    exams = ExamSchedule.objects.all()
    return render(request, 'allocation/exam_schedule_list.html', {'exam_list': exams})


@staff_required
def exam_schedule_create(request):
    if request.method == 'POST':
        form = ExamScheduleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Exam schedule added.')
            return redirect('allocation:exam_schedule_list')
    else:
        form = ExamScheduleForm()
    return render(
        request,
        'allocation/exam_schedule_form.html',
        {'form': form, 'title': 'Add Exam Schedule'},
    )


@staff_required
def exam_schedule_edit(request, pk):
    exam = get_object_or_404(ExamSchedule, pk=pk)
    if request.method == 'POST':
        previous = {
            'date': exam.date, 'slot': exam.slot, 'start_time': exam.start_time,
            'end_time': exam.end_time, 'subject_id': exam.subject_id,
            'session_id': exam.session_id,
            'reporting_time': exam.reporting_time, 'instructions': exam.instructions,
            'examination': exam.session.name if exam.session_id else (str(exam.subject) if exam.subject_id else f'Exam schedule {exam.pk}'),
        }
        affected_people = []
        for duty in exam.duty_allocations.select_related('faculty', 'phd_scholar'):
            person = duty.faculty or duty.phd_scholar
            if person and person not in affected_people:
                affected_people.append(person)
        form = ExamScheduleForm(request.POST, instance=exam)
        if form.is_valid():
            form.save()
            current_examination = exam.session.name if exam.session_id else (str(exam.subject) if exam.subject_id else f'Exam schedule {exam.pk}')
            current = {
                'date': exam.date, 'slot': exam.slot, 'start_time': exam.start_time,
                'end_time': exam.end_time, 'subject_id': exam.subject_id,
                'session_id': exam.session_id, 'examination': current_examination,
                'reporting_time': exam.reporting_time, 'instructions': exam.instructions,
            }
            if current != previous:
                message = (f'Exam schedule changed: {exam.date} {exam.start_time}-{exam.end_time} '
                           f'({exam.get_slot_display()})' + (f' · {exam.subject}' if exam.subject else ''))
                recipients = {d.faculty.user_id for d in exam.duty_allocations.select_related('faculty__user') if d.faculty_id and d.faculty.user_id}
                recipients.update(d.phd_scholar.user_id for d in exam.duty_allocations.select_related('phd_scholar__user') if d.phd_scholar_id and d.phd_scholar.user_id)
                from django.contrib.auth import get_user_model
                recipients.update(get_user_model().objects.filter(is_staff=True).values_list('pk', flat=True))
                Notification.objects.bulk_create([Notification(recipient_id=user_id, message=message) for user_id in recipients])
                def display(value):
                    if value is None:
                        return ''
                    return value.strftime('%d %b %Y') if hasattr(value, 'strftime') and value.__class__.__name__ == 'date' else (value.strftime('%H:%M') if hasattr(value, 'strftime') else str(value))
                previous_text = (f"{previous['examination']} · {display(previous['date'])} {display(previous['start_time'])}–{display(previous['end_time'])} "
                    f"({dict(ExamSchedule.Slot.choices).get(previous['slot'], previous['slot'])}); reporting {display(previous['reporting_time']) or '10 minutes before start'}; "
                    f"instructions: {previous['instructions'] or 'none'}")
                updated_text = (f"{current['examination']} · {display(current['date'])} {display(current['start_time'])}–{display(current['end_time'])} "
                    f"({exam.get_slot_display()}); reporting {display(current['reporting_time']) or '10 minutes before start'}; "
                    f"instructions: {current['instructions'] or 'none'}")
                details = [('Previous details', previous_text), ('Updated details', updated_text)]
                email_key = f"schedule-change:{exam.pk}:{previous['date']}:{previous['start_time']}:{previous['end_time']}:{current['date']}:{current['start_time']}:{current['end_time']}:{current['subject_id']}:{current['session_id']}"
                for person in affected_people:
                    queue_person_email(person,
                        notification_type='SCHEDULE_UPDATE', template_key='schedule_update',
                        subject=f'Examination schedule updated · {exam.date:%d %b %Y}',
                        details=details, idempotency_key=f'{email_key}:person:{person._meta.label_lower}:{person.pk}',
                        intro='A schedule change affects an examination duty assigned to you.')
                queue_admin_email(subject=f'Examination schedule updated · {exam.date:%d %b %Y}',
                    notification_type='SCHEDULE_UPDATE', template_key='schedule_update',
                    details=details, idempotency_prefix=email_key,
                    intro='An examination schedule with allocated duties was changed.')
            messages.success(request, 'Exam schedule updated.')
            return redirect('allocation:exam_schedule_list')
    else:
        form = ExamScheduleForm(instance=exam)
    return render(
        request,
        'allocation/exam_schedule_form.html',
        {'form': form, 'title': 'Edit Exam Schedule'},
    )


@staff_required
def ufm_record_list(request):
    records = UFMRecord.objects.select_related(
        'faculty', 'phd_scholar', 'exam_schedule'
    ).all()
    return render(request, 'allocation/ufm_record_list.html', {'records': records})


@staff_required
def run_allocation(request):
    if request.method == 'POST':
        try:
            created = allocate_all_duties(clear_existing=True)
            missing_email = sum(1 for allocation in created
                if not (allocation.faculty or allocation.phd_scholar).email)
            messages.success(
                request, f'Allocation complete. Created {len(created)} duties.'
            )
            if missing_email:
                messages.warning(request, f'{missing_email} assigned duty notification(s) were not queued because the person has no registered email address.')
        except ValidationError as exc:
            messages.error(request, str(exc))
        return redirect('allocation:allocation_result')
    return render(request, 'allocation/run_allocation_confirm.html', {
        'exam_count': ExamSchedule.objects.count(),
    })


@staff_required
@require_POST
def run_allocation_ajax(request):
    try:
        created = allocate_all_duties(clear_existing=True)
        return JsonResponse({'status': 'ok', 'created': len(created)})
    except ValidationError as exc:
        return JsonResponse({'status': 'error', 'message': str(exc)}, status=400)


@staff_required
def ufm_record_create(request):
    if request.method == 'POST':
        form = UFMRecordForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'UFM record added.')
            return redirect('allocation:ufm_record_list')
    else:
        form = UFMRecordForm()
    return render(
        request,
        'allocation/ufm_record_form.html',
        {'form': form, 'title': 'Add UFM Record'},
    )



@staff_required
def export_allocation_csv(request):
    import csv

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="duty_allocation.csv"'

    allocations = DutyAllocation.objects.select_related(
        'exam_schedule', 'classroom', 'faculty', 'phd_scholar'
    ).order_by(
        'exam_schedule__date', 'exam_schedule__slot', 'classroom__name'
    )

    writer = csv.writer(response)
    writer.writerow(
        [
            'S.No',
            'Name',
            'Designation',
            'Date',
            'Time Slot',
            'Room Number',
            'Role Type',
        ]
    )

    for idx, a in enumerate(allocations, start=1):
        person = a.faculty or a.phd_scholar
        if a.faculty:
            designation = a.faculty.get_designation_display()
        else:
            designation = 'PhD Scholar'
        writer.writerow(
            [
                idx,
                person.name if person else '',
                designation,
                a.exam_schedule.date,
                a.exam_schedule.get_slot_display(),
                a.classroom.name,
                a.get_role_type_display(),
            ]
        )

    return response


@staff_required
def duty_order_pdf(request):
    examination_type = request.GET.get('type', ExamSchedule.ExaminationType.END_SEMESTER).strip().upper()
    valid_types = {choice for choice, _label in ExamSchedule.ExaminationType.choices}
    if examination_type not in valid_types:
        return HttpResponseBadRequest('Choose Mid Semester or End Semester Examination.')
    date_value = request.GET.get('date', '').strip()
    slot_value = request.GET.get('slot', '').strip().upper()
    session_id = request.GET.get('session', '').strip()
    if date_value and parse_date(date_value) is None:
        return HttpResponseBadRequest('Use a valid date in YYYY-MM-DD format.')
    if session_id and not session_id.isdigit():
        return HttpResponseBadRequest('Use a valid examination session.')
    allocations = allocation_queryset().filter(exam_schedule__examination_type=examination_type)
    if date_value:
        allocations = allocations.filter(exam_schedule__date=date_value)
    if slot_value in (ExamSchedule.Slot.MORNING, ExamSchedule.Slot.EVENING):
        allocations = allocations.filter(exam_schedule__slot=slot_value)
    if session_id:
        allocations = allocations.filter(exam_schedule__session_id=session_id)
    label = examination_type.lower().replace('_', '-')
    suffix = f'-{date_value}' if date_value else (f'-{slot_value.lower()}' if slot_value else '')
    filename = f'{label}-examination-duty-chart{suffix}.pdf'
    return build_duty_chart(allocations, examination_type, filename,
                            inline=request.GET.get('preview') == '1')


@staff_required
def duty_slip_pdf(request):
    allocation_id = request.GET.get('allocation', '').strip()
    person_type = request.GET.get('person_type', '').strip().lower()
    if not allocation_id or person_type not in ('faculty', 'phd'):
        messages.error(request, 'Choose a faculty or PhD scholar duty assignment first.')
        return redirect('allocation:allocation_result')
    query = allocation_queryset().filter(pk=allocation_id)
    query = query.filter(faculty__isnull=False) if person_type == 'faculty' else query.filter(phd_scholar__isnull=False)
    allocation = get_object_or_404(query)
    return build_individual_slip(allocation)


@staff_required
def faculty_duty_details_pdf(request):
    faculty_id = request.GET.get('faculty_id', '').strip()
    if not faculty_id.isdigit():
        return HttpResponseBadRequest('Choose a faculty member.')
    faculty = get_object_or_404(Faculty, pk=faculty_id)
    allocations = allocation_queryset().filter(faculty=faculty)
    return build_faculty_details(faculty, allocations,
        filename=f'faculty-duty-details-{faculty.pk}.pdf', inline=request.GET.get('preview') == '1')


def _render_table_pdf(filename, title, subtitle, headers, rows, column_widths_mm):
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    cell_style = styles['BodyText']
    cell_style.fontSize = 8
    cell_style.leading = 10
    header_style = ParagraphStyle(
        'TableHeader', parent=cell_style, fontName='Helvetica-Bold',
        fontSize=8, leading=10,
    )
    document = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=title,
    )
    story = [
        Paragraph(escape(title), styles['Title']),
        Paragraph(escape(subtitle), styles['Normal']),
        Spacer(1, 8 * mm),
    ]
    table_data = [[Paragraph(escape(str(value)), header_style) for value in headers]]
    table_data.extend([
        [Paragraph(escape(str(value)), cell_style) for value in row]
        for row in rows
    ] or [[Paragraph('No records available.', cell_style)] + [''] * (len(headers) - 1)])
    table = LongTable(
        table_data,
        colWidths=[width * mm for width in column_widths_mm],
        repeatRows=1,
        hAlign='LEFT',
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#16324f')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#b7c4d1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f5f9')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    document.build(story)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@staff_required
def seating_plan(request):
    plans = []
    exams = ExamSchedule.objects.prefetch_related('exam_sections__section').all()

    for exam in exams:
        room_entries = []
        rooms = Classroom.objects.filter(seatings__exam_schedule=exam).distinct().order_by('name')
        for room in rooms:
            seats = list(Seating.objects.filter(exam_schedule=exam, classroom=room).select_related('section').order_by('seat_no'))
            ranges = SeatingAllotment.objects.filter(exam_schedule=exam, classroom=room).select_related('section')
            room_entries.append(
                {
                    'classroom': room,
                    'capacity': room.capacity,
                    'ranges': ranges,
                    'grid': [[next((seat for seat in seats if seat.row_no == row and seat.col_no == col), None)
                              for col in range(1, room.columns + 1)] for row in range(1, room.rows + 1)],
                }
            )
        plans.append({'exam': exam, 'rooms': room_entries})

    session_plans = []
    for session in ExamSession.objects.all():
        room_entries = []
        rooms = Classroom.objects.filter(session_seatings__session=session).distinct().order_by('name')
        for room in rooms:
            seats = list(SessionSeating.objects.filter(session=session, classroom=room).select_related('student').order_by('seat_no'))
            room_entries.append({'classroom': room,
                'grid': [[next((seat for seat in seats if seat.row_no == row and seat.col_no == col), None)
                          for col in range(1, room.columns + 1)] for row in range(1, room.rows + 1)]})
        session_plans.append({'session': session, 'rooms': room_entries})
    return render(request, 'allocation/seating_plan.html', {
        'seating_plans': plans,
        'exams': exams,
        'classrooms': Classroom.objects.all().order_by('name'),
        'sessions': ExamSession.objects.prefetch_related('exam_schedules').all(),
        'session_plans': session_plans,
    })


@staff_required
def exam_session_create(request):
    if request.method == 'POST':
        form = ExamSessionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Examination session created.')
            return redirect('allocation:seating_plan')
    else:
        form = ExamSessionForm()
    return render(request, 'allocation/exam_session_form.html', {'form': form})


@staff_required
@require_POST
def generate_session_seating(request):
    session = get_object_or_404(ExamSession, pk=request.POST.get('session_id'))
    rooms = list(Classroom.objects.filter(pk__in=request.POST.getlist('classrooms')).order_by('name'))
    if not rooms:
        messages.error(request, 'Select at least one classroom.')
        return redirect('allocation:seating_plan')
    schedules = list(session.exam_schedules.prefetch_related('exam_sections__section').all())
    if not schedules:
        messages.error(request, 'Assign one or more exam schedules to this session first.')
        return redirect('allocation:seating_plan')
    section_order = {}
    subject_ids = set()
    for schedule in schedules:
        if schedule.subject_id:
            subject_ids.add(schedule.subject_id)
        for exam_section in schedule.exam_sections.select_related('section').order_by('position'):
            section_order.setdefault(exam_section.section_id, exam_section.position)
    student_map = {}
    for student in Student.objects.filter(section_id__in=section_order):
        student_map[student.pk] = student
    for registration in StudentSubjectRegistration.objects.filter(subject_id__in=subject_ids).select_related('student__section'):
        student_map[registration.student_id] = registration.student
    students = sorted(student_map.values(), key=lambda s: (
        0 if s.category == Student.Category.REGULAR else 1 if s.category == Student.Category.MINOR else 2,
        section_order.get(s.section_id, 10**6), s.section.name, s.roll_no, s.pk,
    ))
    ordered_sections = []
    for student in students:
        if not ordered_sections or ordered_sections[-1][0] != student.section_id:
            ordered_sections.append((student.section_id, student.section.name, []))
        ordered_sections[-1][2].append(StudentInput(student.roll_no, student.section_id, student.section.name))
    try:
        assignments = allocate_seats(ordered_sections, [RoomInput(r.id, r.name, r.rows, r.columns) for r in rooms], request.POST.get('fill_order', 'row'))
    except (InsufficientCapacityError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect('allocation:seating_plan')
    with transaction.atomic():
        SessionSeating.objects.filter(session=session).delete()
        SessionSeatingAllotment.objects.filter(session=session).delete()
        SessionSeating.objects.bulk_create([
            SessionSeating(session=session, classroom_id=a.room_id, student_id=next(s.pk for s in students if s.section_id == a.student.section_id and s.roll_no == a.student.roll_no), seat_no=a.seat_no, row_no=a.row_no, col_no=a.col_no)
            for a in assignments
        ])
        SessionSeatingAllotment.objects.bulk_create([
            SessionSeatingAllotment(session=session, classroom_id=a['room_id'], section_id=a['section_id'], from_roll_no=a['from_roll_no'], to_roll_no=a['to_roll_no'])
            for a in contiguous_ranges(assignments)
        ])
    messages.success(request, f'Session seating generated for {len(assignments)} students.')
    return redirect('allocation:seating_plan')


@staff_required
def export_session_seating_csv(request, session_id):
    session = get_object_or_404(ExamSession, pk=session_id)
    seats = SessionSeating.objects.filter(session=session).select_related('student', 'classroom').order_by('classroom__name', 'seat_no')
    if not seats.exists():
        return HttpResponse('No seating plan has been generated for this session.', status=404)
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Roll No', 'Room', 'Seat No', 'Row', 'Column'])
    writer.writerows([[s.student.roll_no, s.classroom.name, s.seat_no, s.row_no, s.col_no] for s in seats])
    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="session_seating_{session.pk}.csv"'
    return response


@staff_required
def export_session_seating_pdf(request, session_id):
    session = get_object_or_404(ExamSession, pk=session_id)
    seats = SessionSeating.objects.filter(session=session).select_related('student', 'classroom').order_by('classroom__name', 'seat_no')
    if not seats.exists():
        return HttpResponse('No seating plan has been generated for this session.', status=404)
    rows = [[s.student.roll_no, s.classroom.name, s.seat_no, s.row_no, s.col_no] for s in seats]
    return _render_table_pdf(f'session_seating_{session.pk}.pdf', f'{session.name} Seating Plan',
        'One common seating plan for all subjects in this examination session',
        ['Roll No.', 'Room', 'Seat', 'Row', 'Column'], rows, [35, 50, 25, 25, 25])


def _seating_export_rows(exam):
    seatings = list(
        Seating.objects.filter(exam_schedule=exam)
        .select_related('classroom', 'section')
        .order_by('classroom__name', 'seat_no')
    )
    return seatings


@staff_required
def export_seating_plan_csv(request, exam_id):
    exam = get_object_or_404(ExamSchedule, pk=exam_id)
    seatings = _seating_export_rows(exam)
    if not seatings:
        return HttpResponse('No seating plan has been generated for this exam.', status=404)

    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Roll No', 'Room', 'Seat No', 'Row', 'Column'])
    for seat in seatings:
        writer.writerow([
            seat.roll_no, seat.classroom.name, seat.seat_no, seat.row_no, seat.col_no,
        ])
    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="seating_plan_{exam.pk}.csv"'
    return response


@staff_required
def export_seating_plan_pdf(request, exam_id):
    exam = get_object_or_404(ExamSchedule, pk=exam_id)
    seatings = _seating_export_rows(exam)
    if not seatings:
        return HttpResponse('No seating plan has been generated for this exam.', status=404)
    rows = [[
        seat.roll_no, seat.classroom.name, seat.seat_no, seat.row_no, seat.col_no,
    ] for seat in seatings]
    subtitle = f'{exam.date:%d %b %Y} | {exam.get_slot_display()} | {exam.subject or "Exam"}'
    return _render_table_pdf(
        f'seating_plan_{exam.pk}.pdf', 'Exam Seating Plan', subtitle,
        ['Roll No.', 'Room', 'Seat', 'Row', 'Column'],
        rows, [35, 50, 25, 25, 25],
    )


@staff_required
@require_POST
def generate_seating(request):
    exam = get_object_or_404(ExamSchedule, pk=request.POST.get('exam_id'))
    room_ids = request.POST.getlist('classrooms')
    rooms = list(Classroom.objects.filter(pk__in=room_ids).order_by('name'))
    if not rooms:
        messages.error(request, 'Select at least one classroom.')
        return redirect('allocation:seating_plan')
    fill_order = request.POST.get('fill_order', 'row')
    sections = []
    for exam_section in exam.exam_sections.select_related('section').order_by('position'):
        students = [StudentInput(s.roll_no, exam_section.section_id, exam_section.section.name)
                    for s in exam_section.section.students.all().order_by('roll_no')]
        sections.append((exam_section.section_id, exam_section.section.name, students))
    if not sections:
        messages.error(request, 'Select at least one section for this exam before generating seating.')
        return redirect('allocation:seating_plan')
    try:
        assignments = allocate_seats(
            sections, [RoomInput(r.id, r.name, r.rows, r.columns) for r in rooms], fill_order
        )
    except (InsufficientCapacityError, ValueError) as exc:
        messages.error(request, str(exc))
        return redirect('allocation:seating_plan')
    with transaction.atomic():
        Seating.objects.filter(exam_schedule=exam).delete()
        SeatingAllotment.objects.filter(exam_schedule=exam).delete()
        Seating.objects.bulk_create([
            Seating(exam_schedule=exam, classroom_id=item.room_id,
                    section_id=item.student.section_id, seat_no=item.seat_no,
                    row_no=item.row_no, col_no=item.col_no, roll_no=item.student.roll_no)
            for item in assignments
        ])
        SeatingAllotment.objects.bulk_create([
            SeatingAllotment(exam_schedule=exam, classroom_id=item['room_id'],
                             section_id=item['section_id'], from_roll_no=item['from_roll_no'],
                             to_roll_no=item['to_roll_no'])
            for item in contiguous_ranges(assignments)
        ])
    messages.success(request, f'Seating generated for {len(assignments)} students.')
    return redirect('allocation:seating_plan')


@staff_required
def seating_search(request):
    roll_no = request.GET.get('roll_no', '').strip()
    seatings = Seating.objects.none()
    if roll_no:
        seatings = Seating.objects.filter(roll_no=roll_no).select_related(
            'exam_schedule', 'classroom', 'section'
        ).order_by('exam_schedule__date', 'exam_schedule__slot', 'section__name')
        if not seatings.exists():
            messages.warning(request, f'No seating allotment found for roll number {roll_no}.')
    return render(request, 'allocation/seating_search.html', {'seatings': seatings, 'roll_no': roll_no})


@staff_required
@require_POST
def export_seating_csv(request):
    upload = request.FILES.get('student_csv')
    exam = get_object_or_404(ExamSchedule, pk=request.POST.get('exam_id'))
    if not upload or upload.size > 5 * 1024 * 1024:
        return HttpResponseBadRequest('Upload a CSV file no larger than 5 MB.')
    try:
        content = upload.read().decode('utf-8-sig')
        seating_by_roll = {
            (item.section.name, str(item.roll_no)): {
                'room_name': item.classroom.name, 'row': item.row_no,
                'column': item.col_no, 'seat_no': item.seat_no,
            }
            for item in Seating.objects.filter(exam_schedule=exam).select_related('classroom', 'section')
        }
        merged, unallotted = merge_seating_csv(__import__('io').StringIO(content), seating_by_roll)
    except (UnicodeDecodeError, ValueError) as exc:
        return HttpResponseBadRequest(str(exc))
    response = HttpResponse(merged, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="student_seating.csv"'
    if unallotted:
        response['X-Unallotted-Rolls'] = ','.join(unallotted)[:4000]
        messages.warning(request, 'Unallotted roll numbers: ' + ', '.join(filter(None, unallotted)))
    return response


@staff_required
@require_POST
def import_students_csv(request):
    import csv
    import io

    upload = request.FILES.get('student_csv')
    if not upload or upload.size > 5 * 1024 * 1024:
        return HttpResponseBadRequest('Upload a CSV file no larger than 5 MB.')
    try:
        rows = list(csv.DictReader(io.StringIO(upload.read().decode('utf-8-sig'))))
        if not rows or not {'roll_no', 'section'}.issubset(rows[0]):
            raise ValueError('CSV must include roll_no and section columns.')
        students = []
        sections = {}
        for number, row in enumerate(rows, start=2):
            section_name = row.get('section', '').strip()
            if not section_name:
                raise ValueError(f'Row {number}: section is required.')
            try:
                roll_no = int(row.get('roll_no', ''))
            except ValueError as exc:
                raise ValueError(f'Row {number}: roll_no must be a positive integer.') from exc
            if roll_no < 1:
                raise ValueError(f'Row {number}: roll_no must be a positive integer.')
            sections.setdefault(section_name, None)
            students.append((section_name, roll_no, row.get('name', '').strip()))
        with transaction.atomic():
            for name in sections:
                sections[name], _ = Section.objects.get_or_create(name=name)
            for section_name, roll_no, name in students:
                Student.objects.update_or_create(
                    section=sections[section_name], roll_no=roll_no, defaults={'name': name}
                )
    except (UnicodeDecodeError, ValueError) as exc:
        return HttpResponseBadRequest(str(exc))
    messages.success(request, f'Imported {len(students)} students.')
    return redirect('allocation:seating_plan')



@staff_required
def allocation_result(request):
    q = request.GET.get('q', '').strip()
    date_filter = request.GET.get('date', '').strip()
    slot_filter = request.GET.get('slot', '').strip().upper()
    allocations = DutyAllocation.objects.select_related(
        'exam_schedule', 'classroom', 'faculty', 'phd_scholar'
    ).order_by('exam_schedule__date', 'exam_schedule__slot', 'classroom__name')
    if q:
        allocations = allocations.filter(
            Q(faculty__name__icontains=q)
            | Q(phd_scholar__name__icontains=q)
            | Q(classroom__name__icontains=q)
        )
    parsed_date = parse_date(date_filter) if date_filter else None
    if parsed_date:
        allocations = allocations.filter(exam_schedule__date=parsed_date)
    if slot_filter in (ExamSchedule.Slot.MORNING, ExamSchedule.Slot.EVENING):
        allocations = allocations.filter(exam_schedule__slot=slot_filter)

    paginator = Paginator(allocations, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'allocation/allocation_result.html', {
        'page_obj': page_obj,
        'q': q,
        'date_filter': date_filter,
        'slot_filter': slot_filter,
        'duty_slip_allocations': allocation_queryset(),
        'exam_sessions': ExamSession.objects.order_by('name'),
        'faculty_profiles': Faculty.objects.order_by('name'),
    })

