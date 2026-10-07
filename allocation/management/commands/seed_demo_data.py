from datetime import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from allocation.models import Classroom, ExamSchedule, ExamSection, Faculty, Section, Student, Subject


class Command(BaseCommand):
    help = 'Create or update a small, repeatable seating demonstration dataset.'

    def handle(self, *args, **options):
        rooms = [('Room 1', 10, 7), ('Room 2', 8, 5), ('Room 3', 6, 5)]
        for name, rows, columns in rooms:
            Classroom.objects.update_or_create(name=name, defaults={'rows': rows, 'columns': columns})

        sections = {}
        for name, total in [('Section A', 80), ('Section B', 25), ('Section C', 30)]:
            section, _ = Section.objects.get_or_create(name=name)
            sections[name] = section
            for roll_no in range(1, total + 1):
                Student.objects.update_or_create(
                    section=section,
                    roll_no=roll_no,
                    defaults={'name': f'{name} Student {roll_no}'},
                )

        subject, _ = Subject.objects.get_or_create(name='Demo Subject')
        exam, _ = ExamSchedule.objects.get_or_create(
            date=timezone.localdate(),
            slot=ExamSchedule.Slot.MORNING,
            defaults={'start_time': time(9, 0), 'end_time': time(12, 0), 'subject': subject},
        )
        exam.subject = subject
        exam.save(update_fields=['subject'])
        for position, section in enumerate(sections.values(), start=1):
            ExamSection.objects.update_or_create(
                exam_schedule=exam,
                section=section,
                defaults={'position': position},
            )

        teacher, _ = Faculty.objects.get_or_create(
            email='demo.subject.faculty@example.com',
            defaults={'name': 'Demo Subject Faculty', 'designation': Faculty.Designation.PROFESSOR},
        )
        teacher.subjects.add(subject)
        self.stdout.write(self.style.SUCCESS('Demo classrooms, students, exam, and subject faculty are ready.'))
