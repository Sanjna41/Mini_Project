from django.db import models
from django.utils import timezone


class Faculty(models.Model):
    class Designation(models.TextChoices):
        PROFESSOR = 'PROF', 'Professor'
        ASSOCIATE_PROFESSOR = 'ASSOC', 'Associate Professor'
        ASSISTANT_PROFESSOR = 'ASSIST', 'Assistant Professor'

    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    designation = models.CharField(max_length=10, choices=Designation.choices)
    duty_quota = models.PositiveIntegerField(default=10)
    subjects = models.ManyToManyField('Subject', blank=True, related_name='faculty_members')

    def __str__(self) -> str:
        return f"{self.name} ({self.get_designation_display()})"


class PhDScholar(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
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

    def __str__(self) -> str:
        return self.name


class Section(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self) -> str:
        return self.name


class Student(models.Model):
    name = models.CharField(max_length=100, blank=True)
    roll_no = models.PositiveIntegerField()
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='students')

    class Meta:
        unique_together = ('section', 'roll_no')
        ordering = ['roll_no']

    def __str__(self) -> str:
        return f"{self.roll_no} - {self.section}"


class ExamSchedule(models.Model):
    class Slot(models.TextChoices):
        MORNING = 'MORNING', 'Morning'
        EVENING = 'EVENING', 'Evening'

    date = models.DateField()
    slot = models.CharField(max_length=10, choices=Slot.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
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

