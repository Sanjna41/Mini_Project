from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


class Faculty(models.Model):
    class Designation(models.TextChoices):
        PROFESSOR = 'PROF', 'Professor'
        ASSOCIATE_PROFESSOR = 'ASSOC', 'Associate Professor'
        ASSISTANT_PROFESSOR = 'ASSIST', 'Assistant Professor'

    name = models.CharField(max_length=100)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='faculty_profile')
    employee_id = models.CharField(max_length=40, blank=True, unique=True, null=True)
    email = models.EmailField(blank=True)
    department = models.CharField(max_length=100, blank=True)
    contact = models.CharField(max_length=30, blank=True)
    must_change_password = models.BooleanField(default=False)
    designation = models.CharField(max_length=10, choices=Designation.choices)
    duty_quota = models.PositiveIntegerField(default=10)
    subjects = models.ManyToManyField('Subject', blank=True, related_name='faculty_members')

    def __str__(self) -> str:
        return f"{self.name} ({self.get_designation_display()})"


class PhDScholar(models.Model):
    name = models.CharField(max_length=100)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='phd_profile')
    scholar_id = models.CharField(max_length=40, blank=True, unique=True, null=True)
    email = models.EmailField(blank=True)
    department = models.CharField(max_length=100, blank=True)
    academic_year = models.CharField(max_length=20, blank=True)
    contact = models.CharField(max_length=30, blank=True)
    must_change_password = models.BooleanField(default=False)
    duty_quota = models.PositiveIntegerField(default=12)
    subjects = models.ManyToManyField('Subject', blank=True, related_name='phd_scholars')

    def __str__(self) -> str:
        return self.name


class Classroom(models.Model):
    name = models.CharField(max_length=50, unique=True)
    rows = models.PositiveIntegerField()
    columns = models.PositiveIntegerField()

    @property
    def capacity(self):
        return self.rows * self.columns

    def __str__(self) -> str:
        return f"{self.name} (Cap: {self.capacity})"


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    coordinator = models.ForeignKey(
        Faculty, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='coordinated_subjects',
    )

    def __str__(self) -> str:
        return self.name


class Section(models.Model):
    name = models.CharField(max_length=50, unique=True)
    department = models.CharField(max_length=100, blank=True)

    def __str__(self) -> str:
        return self.name


class Student(models.Model):
    class Category(models.TextChoices):
        REGULAR = 'REGULAR', 'Regular'
        MINOR = 'MINOR', 'Minor'
        ELECTIVE = 'ELECTIVE', 'Elective'
    name = models.CharField(max_length=100, blank=True)
    roll_no = models.PositiveIntegerField()
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='students')
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.REGULAR)
    subjects = models.ManyToManyField('Subject', through='StudentSubjectRegistration', related_name='registered_students', blank=True)

    class Meta:
        unique_together = ('section', 'roll_no')
        ordering = ['roll_no']

    def __str__(self) -> str:
        return f"{self.roll_no} - {self.section}"


class ExamSchedule(models.Model):
    class ExaminationType(models.TextChoices):
        MID_SEMESTER = 'MID', 'Mid Semester Examination'
        END_SEMESTER = 'END', 'End Semester Examination'

    class CoordinatorStatus(models.TextChoices):
        NOT_REQUIRED = 'NONE', 'No subject coordinator required'
        PENDING = 'PENDING', 'Coordinator duty pending'
        ASSIGNED = 'ASSIGNED', 'Coordinator duty assigned'
        UNRESOLVED = 'UNRESOLVED', 'Coordinator duty unresolved'

    class Slot(models.TextChoices):
        MORNING = 'MORNING', 'Morning'
        EVENING = 'EVENING', 'Evening'

    date = models.DateField()
    session = models.ForeignKey('ExamSession', null=True, blank=True, on_delete=models.SET_NULL, related_name='exam_schedules')
    examination_type = models.CharField(max_length=3, choices=ExaminationType.choices,
        default=ExaminationType.END_SEMESTER, db_index=True)
    slot = models.CharField(max_length=10, choices=Slot.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    reporting_time = models.TimeField(null=True, blank=True)
    instructions = models.TextField(blank=True)
    coordinator_status = models.CharField(max_length=12, choices=CoordinatorStatus.choices,
        default=CoordinatorStatus.NOT_REQUIRED, db_index=True)
    coordinator_note = models.TextField(blank=True)
    subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.SET_NULL)
    sections = models.ManyToManyField(Section, through='ExamSection', blank=True)

    def __str__(self) -> str:
        return f"{self.date} - {self.get_slot_display()} ({self.start_time}-{self.end_time})"

    class Meta:
        ordering = ['date', 'slot']


class ExamSection(models.Model):
    exam_schedule = models.ForeignKey(ExamSchedule, on_delete=models.CASCADE, related_name='exam_sections')
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(fields=['exam_schedule', 'section'], name='unique_exam_section'),
            models.UniqueConstraint(fields=['exam_schedule', 'position'], name='unique_exam_section_position'),
        ]


class Seating(models.Model):
    exam_schedule = models.ForeignKey(ExamSchedule, on_delete=models.CASCADE, related_name='seatings')
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='seatings')
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='seatings')
    seat_no = models.PositiveIntegerField()
    row_no = models.PositiveIntegerField()
    col_no = models.PositiveIntegerField()
    roll_no = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['exam_schedule', 'section', 'roll_no'],
                name='unique_exam_section_roll_seating',
            ),
            models.UniqueConstraint(fields=['exam_schedule', 'classroom', 'row_no', 'col_no'], name='unique_exam_room_position'),
        ]


class SeatingAllotment(models.Model):
    exam_schedule = models.ForeignKey(ExamSchedule, on_delete=models.CASCADE, related_name='seating_allotments')
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='seating_allotments')
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='seating_allotments')
    from_roll_no = models.PositiveIntegerField()
    to_roll_no = models.PositiveIntegerField()

    class Meta:
        ordering = ['classroom__name', 'from_roll_no']


class ExamSession(models.Model):
    name = models.CharField(max_length=120, unique=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class StudentSubjectRegistration(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='subject_registrations')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='student_registrations')
    category = models.CharField(max_length=10, choices=[('MINOR', 'Minor'), ('ELECTIVE', 'Elective')])

    class Meta:
        constraints = [models.UniqueConstraint(fields=['student', 'subject'], name='unique_student_subject_registration')]


class TimetableEntry(models.Model):
    """Weekly class commitment for one faculty member or PhD scholar."""
    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Monday'
        TUESDAY = 1, 'Tuesday'
        WEDNESDAY = 2, 'Wednesday'
        THURSDAY = 3, 'Thursday'
        FRIDAY = 4, 'Friday'
        SATURDAY = 5, 'Saturday'
        SUNDAY = 6, 'Sunday'
    faculty = models.ForeignKey(Faculty, null=True, blank=True, on_delete=models.CASCADE, related_name='timetable')
    phd_scholar = models.ForeignKey(PhDScholar, null=True, blank=True, on_delete=models.CASCADE, related_name='timetable')
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    label = models.CharField(max_length=120, blank=True)

    def clean(self):
        if bool(self.faculty_id) == bool(self.phd_scholar_id):
            raise ValidationError('Select exactly one faculty member or PhD scholar.')
        if self.start_time >= self.end_time:
            raise ValidationError('Timetable end time must be after start time.')

    class Meta:
        constraints = [models.CheckConstraint(condition=(models.Q(faculty__isnull=False, phd_scholar__isnull=True) | models.Q(faculty__isnull=True, phd_scholar__isnull=False)), name='timetable_exactly_one_person'),
                       models.CheckConstraint(condition=models.Q(end_time__gt=models.F('start_time')), name='timetable_positive_interval')]


class Availability(models.Model):
    faculty = models.ForeignKey(Faculty, null=True, blank=True, on_delete=models.CASCADE, related_name='availability')
    phd_scholar = models.ForeignKey(PhDScholar, null=True, blank=True, on_delete=models.CASCADE, related_name='availability')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_available = models.BooleanField(default=True)
    note = models.CharField(max_length=240, blank=True)

    def clean(self):
        if bool(self.faculty_id) == bool(self.phd_scholar_id):
            raise ValidationError('Select exactly one faculty member or PhD scholar.')
        if self.start_time >= self.end_time:
            raise ValidationError('Availability end time must be after start time.')

    class Meta:
        constraints = [models.CheckConstraint(condition=(models.Q(faculty__isnull=False, phd_scholar__isnull=True) | models.Q(faculty__isnull=True, phd_scholar__isnull=False)), name='availability_exactly_one_person'),
                       models.CheckConstraint(condition=models.Q(end_time__gt=models.F('start_time')), name='availability_positive_interval')]


class ReplacementRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        ACCEPTED = 'ACCEPTED', 'Accepted'
        REJECTED = 'REJECTED', 'Rejected'
    allocation = models.ForeignKey('DutyAllocation', on_delete=models.CASCADE, related_name='replacement_requests')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='replacement_requests_sent')
    target_faculty = models.ForeignKey(Faculty, null=True, blank=True, on_delete=models.CASCADE, related_name='replacement_requests_received')
    target_phd_scholar = models.ForeignKey(PhDScholar, null=True, blank=True, on_delete=models.CASCADE, related_name='replacement_requests_received')
    replaced_faculty = models.ForeignKey(Faculty, null=True, blank=True, on_delete=models.SET_NULL, related_name='replacement_requests_made')
    replaced_phd_scholar = models.ForeignKey(PhDScholar, null=True, blank=True, on_delete=models.SET_NULL, related_name='replacement_requests_made')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        if bool(self.target_faculty_id) == bool(self.target_phd_scholar_id):
            raise ValidationError('Select exactly one replacement person.')

    class Meta:
        constraints = [models.CheckConstraint(condition=(models.Q(target_faculty__isnull=False, target_phd_scholar__isnull=True) | models.Q(target_faculty__isnull=True, target_phd_scholar__isnull=False)), name='replacement_exactly_one_target')]


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='exam_notifications')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)


class SessionSeating(models.Model):
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name='seatings')
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='session_seatings')
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='session_seatings')
    seat_no = models.PositiveIntegerField()
    row_no = models.PositiveIntegerField()
    col_no = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['session', 'student'], name='unique_student_session_seat'),
            models.UniqueConstraint(fields=['session', 'classroom', 'row_no', 'col_no'], name='unique_session_room_seat'),
        ]


class SessionSeatingAllotment(models.Model):
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name='seating_allotments')
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='session_seating_allotments')
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='session_seating_allotments')
    from_roll_no = models.PositiveIntegerField()
    to_roll_no = models.PositiveIntegerField()

    class Meta:
        ordering = ['classroom__name', 'from_roll_no']


class ImportBatch(models.Model):
    import_type = models.CharField(max_length=30)
    filename = models.CharField(max_length=255)
    rows = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    report = models.JSONField(default=dict, blank=True)


class EmailNotification(models.Model):
    class Type(models.TextChoices):
        DUTY_ASSIGNMENT = 'DUTY_ASSIGNMENT', 'Duty assignment'
        REPLACEMENT_REQUEST = 'REPLACEMENT_REQUEST', 'Replacement request'
        REPLACEMENT_CONFIRMATION = 'REPLACEMENT_CONFIRMATION', 'Replacement confirmation'
        REPLACEMENT_REJECTION = 'REPLACEMENT_REJECTION', 'Replacement rejection'
        SCHEDULE_UPDATE = 'SCHEDULE_UPDATE', 'Schedule update'
        ANNOUNCEMENT = 'ANNOUNCEMENT', 'Announcement'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        SENT = 'SENT', 'Sent'
        FAILED = 'FAILED', 'Failed'

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='exam_email_notifications')
    recipient_email = models.EmailField()
    recipient_name = models.CharField(max_length=160, blank=True)
    subject = models.CharField(max_length=255)
    notification_type = models.CharField(max_length=32, choices=Type.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    text_body = models.TextField()
    html_body = models.TextField()
    attempt_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['notification_type', 'status', 'created_at'], name='email_type_status_created')]


class UFMRecord(models.Model):
    faculty = models.ForeignKey(
        Faculty, null=True, blank=True, on_delete=models.CASCADE
    )
    phd_scholar = models.ForeignKey(
        PhDScholar, null=True, blank=True, on_delete=models.CASCADE
    )
    exam_schedule = models.ForeignKey(
        ExamSchedule, on_delete=models.CASCADE, related_name='ufm_records'
    )
    count = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:
        person = self.faculty or self.phd_scholar
        return f"UFM: {person} - {self.count}"


class DutyAllocation(models.Model):
    class RoleType(models.TextChoices):
        PROFESSOR = 'PROF', 'Professor'
        ASSISTANT_PROFESSOR = 'ASSIST', 'Assistant Professor'
        PHD_SCHOLAR = 'PHD', 'PhD Scholar'

    class DetainedRound(models.TextChoices):
        NONE = 'NONE', 'None'
        DOUBT = 'DOUBT', 'Round 1 - Doubt'
        QP_SHORTAGE = 'QP', 'Round 2 - Question Paper Shortage'

    exam_schedule = models.ForeignKey(
        ExamSchedule, on_delete=models.CASCADE, related_name='duty_allocations'
    )
    subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='duty_allocations')
    is_subject_coordinator = models.BooleanField(default=False)
    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name='duty_allocations'
    )
    faculty = models.ForeignKey(
        Faculty, null=True, blank=True, on_delete=models.CASCADE,
        related_name='duty_allocations'
    )
    phd_scholar = models.ForeignKey(
        PhDScholar, null=True, blank=True, on_delete=models.CASCADE,
        related_name='duty_allocations'
    )
    role_type = models.CharField(max_length=10, choices=RoleType.choices)
    detained_round = models.CharField(
        max_length=10,
        choices=DetainedRound.choices,
        default=DetainedRound.NONE,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        person = self.faculty or self.phd_scholar
        return f"{person} - {self.exam_schedule} - {self.classroom}"

    class Meta:
        unique_together = ('exam_schedule', 'classroom', 'faculty', 'phd_scholar')
        constraints = [
            models.UniqueConstraint(fields=['exam_schedule'], condition=models.Q(is_subject_coordinator=True),
                name='one_subject_coordinator_per_exam'),
            models.CheckConstraint(condition=(models.Q(is_subject_coordinator=False) |
                models.Q(faculty__isnull=False, phd_scholar__isnull=True)),
                name='coordinator_duty_must_be_faculty'),
        ]

