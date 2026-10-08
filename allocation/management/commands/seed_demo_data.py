from datetime import time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from allocation.allocation_algorithm import allocate_all_duties
from allocation.models import (
    Classroom,
    DutyAllocation,
    ExamSchedule,
    ExamSection,
    Faculty,
    PhDScholar,
    Seating,
    SeatingAllotment,
    Section,
    Student,
    Subject,
)
from allocation.seating_allocator import RoomInput, StudentInput, allocate_seats, contiguous_ranges


class Command(BaseCommand):
    help = "Load a repeatable, fictional dataset for a presentation."

    def handle(self, *args, **options):
        with transaction.atomic():
            subjects = self._subjects()
            rooms = self._classrooms()
            sections = self._students()
            exams = self._exams(subjects, sections)
            self._staff(subjects)
            seating_count = self._seating(exams, rooms)

            if not DutyAllocation.objects.exists():
                try:
                    duty_count = len(allocate_all_duties())
                except Exception as exc:
                    raise CommandError(f"Sample duty allocation could not be generated: {exc}") from exc
            else:
                duty_count = DutyAllocation.objects.count()
                self.stdout.write(
                    self.style.WARNING("Existing duties were kept; no second allocation was run.")
                )

        self.stdout.write(self.style.SUCCESS(
            f"Presentation data ready: {Student.objects.count()} students, "
            f"{len(rooms)} classrooms, {len(exams)} exams, {seating_count} seats, "
            f"{duty_count} duties."
        ))

    def _subjects(self):
        return {
            name: Subject.objects.get_or_create(name=name)[0]
            for name in (
                "Database Management Systems",
                "Operating Systems",
            )
        }

    def _classrooms(self):
        rooms = []
        for name in ("CSE-101", "CSE-102", "CSE-201", "CSE-202"):
            room, _ = Classroom.objects.update_or_create(
                name=name, defaults={"rows": 6, "columns": 10}
            )
            rooms.append(room)
        return rooms

    def _students(self):
        names = {
            "CSE Semester 3 - Section A": (23001, 80),
            "CSE Semester 3 - Section B": (23101, 65),
            "IT Semester 3 - Section A": (23201, 55),
        }
        first_names = (
            "Aarav", "Aditi", "Arjun", "Diya", "Ishaan", "Kavya", "Meera",
            "Neha", "Rohan", "Sana", "Vihaan", "Zoya",
        )
        last_names = (
            "Sharma", "Patel", "Mehta", "Rao", "Nair", "Kapoor", "Iyer",
            "Das", "Joshi", "Khan", "Reddy", "Sen",
        )
        sections = {}
        for section_name, (first_roll, count) in names.items():
            section, _ = Section.objects.get_or_create(name=section_name)
            sections[section_name] = section
            for offset in range(count):
                roll = first_roll + offset
                student_name = f"{first_names[offset % len(first_names)]} {last_names[(offset // len(first_names)) % len(last_names)]}"
                Student.objects.update_or_create(
                    section=section,
                    roll_no=roll,
                    defaults={"name": student_name},
                )
        return sections

    def _exams(self, subjects, sections):
        exam_specs = (
            ("Database Management Systems", 1, ("CSE Semester 3 - Section A", "CSE Semester 3 - Section B")),
            ("Operating Systems", 4, ("CSE Semester 3 - Section B", "IT Semester 3 - Section A")),
        )
        exams = []
        for subject_name, day_offset, section_names in exam_specs:
            exam, _ = ExamSchedule.objects.update_or_create(
                date=timezone.localdate() + timedelta(days=day_offset),
                slot=ExamSchedule.Slot.MORNING,
                defaults={
                    "start_time": time(9, 0),
                    "end_time": time(12, 0),
                    "subject": subjects[subject_name],
                },
            )
            exam.exam_sections.all().delete()
            ExamSection.objects.bulk_create([
                ExamSection(exam_schedule=exam, section=sections[name], position=position)
                for position, name in enumerate(section_names, start=1)
            ])
            exams.append(exam)
        return exams

    def _staff(self, subjects):
        faculty_specs = (
            ("Dr. Aditi Sharma", "professor", Faculty.Designation.PROFESSOR, "Database Management Systems"),
            ("Dr. Rohan Mehta", "professor", Faculty.Designation.PROFESSOR, "Operating Systems"),
            ("Dr. Kavita Rao", "professor", Faculty.Designation.PROFESSOR, None),
            ("Dr. Imran Khan", "professor", Faculty.Designation.PROFESSOR, None),
            ("Dr. Neha Iyer", "professor", Faculty.Designation.PROFESSOR, None),
            ("Ananya Patel", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
            ("Rahul Nair", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
            ("Priya Das", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
            ("Karan Joshi", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
            ("Sana Reddy", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
            ("Vikram Sen", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
            ("Meera Kapoor", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
            ("Arjun Nair", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
            ("Zoya Mehta", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
            ("Ishaan Rao", "assistant", Faculty.Designation.ASSISTANT_PROFESSOR, None),
        )
        for name, category, designation, subject_name in faculty_specs:
            email = f"{category}.{name.split()[1].lower()}@example.test"
            faculty, _ = Faculty.objects.update_or_create(
                email=email,
                defaults={"name": name, "designation": designation, "duty_quota": 10},
            )
            faculty.subjects.set([subjects[subject_name]] if subject_name else [])

        for index in range(1, 15):
            scholar, _ = PhDScholar.objects.update_or_create(
                email=f"scholar{index:02d}@example.test",
                defaults={
                    "name": f"Research Scholar {index:02d}",
                    "duty_quota": 12,
                },
            )
            scholar.subjects.set([subjects["Database Management Systems"] if index % 2 else subjects["Operating Systems"]])

    def _seating(self, exams, rooms):
        created_seats = 0
        for exam in exams:
            section_rows = []
            for exam_section in exam.exam_sections.select_related("section").order_by("position"):
                students = [
                    StudentInput(student.roll_no, exam_section.section_id, exam_section.section.name)
                    for student in exam_section.section.students.order_by("roll_no")
                ]
                section_rows.append((exam_section.section_id, exam_section.section.name, students))
            assignments = allocate_seats(
                section_rows,
                [RoomInput(room.id, room.name, room.rows, room.columns) for room in rooms],
                fill_order="column",
            )
            Seating.objects.filter(exam_schedule=exam).delete()
            SeatingAllotment.objects.filter(exam_schedule=exam).delete()
            Seating.objects.bulk_create([
                Seating(
                    exam_schedule=exam,
                    classroom_id=seat.room_id,
                    section_id=seat.student.section_id,
                    seat_no=seat.seat_no,
                    row_no=seat.row_no,
                    col_no=seat.col_no,
                    roll_no=seat.student.roll_no,
                )
                for seat in assignments
            ])
            room_by_id = {room.id: room for room in rooms}
            section_by_id = {section.id: section for section in Section.objects.filter(
                id__in={seat.student.section_id for seat in assignments}
            )}
            SeatingAllotment.objects.bulk_create([
                SeatingAllotment(
                    exam_schedule=exam,
                    classroom=room_by_id[item["room_id"]],
                    section=section_by_id[item["section_id"]],
                    from_roll_no=item["from_roll_no"],
                    to_roll_no=item["to_roll_no"],
                )
                for item in contiguous_ranges(assignments)
            ])
            created_seats += len(assignments)
        return created_seats
