import io
import zipfile
from datetime import date, time

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.core import mail
from django.core.exceptions import ValidationError
from unittest.mock import patch
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfReader

from .models import (
    Classroom, ExamSchedule, ExamSection, Faculty, PhDScholar, Section, Seating,
    Student, Subject, UFMRecord, Availability, TimetableEntry, ExamSession,
    StudentSubjectRegistration, SessionSeating, DutyAllocation, ReplacementRequest, Notification,
    EmailNotification,
)
from .allocation_algorithm import AllocationEngine, allocate_all_duties
from .email_notifications import queue_duty_assignment, queue_person_email, send_queued_email
from .imports import read_tabular_upload

from .csv_merge import merge_seating_csv
from .duty_rules import choose_faculty_with_subject_rule
from .seating_allocator import (
    InsufficientCapacityError, RoomInput, StudentInput, allocate_seats,
    contiguous_ranges,
)


class SeatingAllocatorTests(SimpleTestCase):
    def section(self, identifier, rolls):
        return (identifier, f'Section {identifier}', [StudentInput(roll, identifier, f'Section {identifier}') for roll in rolls])

    def room(self, identifier, rows, columns):
        return RoomInput(identifier, f'Room {identifier}', rows, columns)

    def test_exact_fit(self):
        result = allocate_seats([self.section(1, [2, 1])], [self.room(1, 1, 2)])
        self.assertEqual([item.student.roll_no for item in result], [1, 2])

    def test_section_overflows_to_next_room(self):
        result = allocate_seats([self.section(1, [1, 2, 3])], [self.room(1, 1, 2), self.room(2, 1, 2)])
        self.assertEqual([item.room_id for item in result], [1, 1, 2])
        self.assertEqual([(item['from_roll_no'], item['to_roll_no']) for item in contiguous_ranges(result)], [(1, 2), (3, 3)])

    def test_next_section_continues_after_overflow(self):
        result = allocate_seats([self.section(1, [1, 2, 3]), self.section(2, [4, 5])], [self.room(1, 1, 2), self.room(2, 1, 3)])
        self.assertEqual([(item.room_id, item.student.section_id, item.student.roll_no) for item in result], [(1, 1, 1), (1, 1, 2), (2, 1, 3), (2, 2, 4), (2, 2, 5)])

    def test_roll_numbers_restart_for_next_section(self):
        result = allocate_seats(
            [self.section(1, [1, 2]), self.section(2, [1, 2])],
            [self.room(1, 1, 4)],
        )
        self.assertEqual(
            [(item.student.section_id, item.student.roll_no) for item in result],
            [(1, 1), (1, 2), (2, 1), (2, 2)],
        )

    def test_insufficient_capacity(self):
        with self.assertRaises(InsufficientCapacityError):
            allocate_seats([self.section(1, [1, 2])], [self.room(1, 1, 1)])

    def test_empty_section(self):
        self.assertEqual(allocate_seats([self.section(1, [])], [self.room(1, 1, 1)]), [])

    def test_single_student(self):
        result = allocate_seats([self.section(1, [9])], [self.room(1, 2, 2)])
        self.assertEqual((result[0].seat_no, result[0].row_no, result[0].col_no), (1, 1, 1))

    def test_fill_orders(self):
        students = [self.section(1, [1, 2, 3, 4])]
        row = allocate_seats(students, [self.room(1, 2, 2)], 'row')
        column = allocate_seats(students, [self.room(1, 2, 2)], 'column')
        self.assertEqual([(item.row_no, item.col_no) for item in row], [(1, 1), (1, 2), (2, 1), (2, 2)])
        self.assertEqual([(item.row_no, item.col_no) for item in column], [(1, 1), (2, 1), (1, 2), (2, 2)])


class XlsxImportParserTests(SimpleTestCase):
    def test_standard_xlsx_first_sheet_is_read_without_optional_packages(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr('xl/workbook.xml', '''<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Students" sheetId="1" r:id="rId1"/></sheets></workbook>''')
            archive.writestr('xl/_rels/workbook.xml.rels', '''<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>''')
            archive.writestr('xl/worksheets/sheet1.xml', '''<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>roll_no</t></is></c><c r="B1" t="inlineStr"><is><t>section</t></is></c></row><row r="2"><c r="A2"><v>101</v></c><c r="B2" t="inlineStr"><is><t>CSE-1</t></is></c></row></sheetData></worksheet>''')
        upload = SimpleUploadedFile('students.xlsx', payload.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertEqual(read_tabular_upload(upload), [{'roll_no': '101', 'section': 'CSE-1'}])


class CsvMergeTests(SimpleTestCase):
    def test_preserves_columns_and_reports_unallotted(self):
        content, unallotted = merge_seating_csv(io.StringIO('name,roll_no,course\nA,1,X\nB,2,Y\n'), {'1': {'room_name': 'R1', 'row': 1, 'column': 2, 'seat_no': 2}})
        self.assertEqual(content.splitlines()[0], 'name,roll_no,course,room_name,row,column,seat_no')
        self.assertIn('A,1,X,R1,1,2,2', content)
        self.assertEqual(unallotted, ['2'])

    def test_duplicate_roll_numbers_match_by_section(self):
        content, unallotted = merge_seating_csv(
            io.StringIO('section,roll_no\nA,1\nB,1\n'),
            {
                ('A', '1'): {'room_name': 'R1', 'row': 1, 'column': 1, 'seat_no': 1},
                ('B', '1'): {'room_name': 'R2', 'row': 1, 'column': 1, 'seat_no': 1},
            },
        )
        self.assertIn('A,1,R1,1,1,1', content)
        self.assertIn('B,1,R2,1,1,1', content)
        self.assertEqual(unallotted, [])


class SubjectFacultyRuleTests(SimpleTestCase):
    def test_subject_faculty_is_avoided_when_possible(self):
        self.assertEqual(choose_faculty_with_subject_rule([1, 2, 3], [2], 2), [(1, False), (3, False)])

    def test_subject_faculty_is_used_only_for_compulsion(self):
        self.assertEqual(choose_faculty_with_subject_rule([1, 2], [2], 2), [(1, False), (2, True)])


class DeploymentSmokeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='deployment-admin', password='Secure-test-pass-2026',
            is_staff=True, is_superuser=True,
        )
        self.subject = Subject.objects.create(name='Deployment Test Subject')
        self.section = Section.objects.create(name='Deployment Test Section')
        self.faculty = Faculty.objects.create(
            name='Test Faculty', email='faculty@example.test',
            designation=Faculty.Designation.PROFESSOR,
        )
        self.subject.coordinator = self.faculty
        self.subject.save(update_fields=['coordinator'])
        self.phd = PhDScholar.objects.create(
            name='Test Scholar', email='scholar@example.test',
        )
        self.room = Classroom.objects.create(name='Test Room', rows=5, columns=6)
        self.exam = ExamSchedule.objects.create(
            date='2026-10-10', slot=ExamSchedule.Slot.MORNING,
            start_time='09:00', end_time='12:00', subject=self.subject,
        )
        ExamSection.objects.create(
            exam_schedule=self.exam, section=self.section, position=1,
        )

    def test_staff_login_dashboard_and_post_logout(self):
        response = self.client.post(reverse('login'), {
            'username': 'deployment-admin', 'password': 'Secure-test-pass-2026',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard')
        self.assertContains(response, 'csrfmiddlewaretoken')
        self.assertTrue(self.client.session.get('_auth_user_id'))

        response = self.client.post(reverse('logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get('_auth_user_id'))

    def test_non_staff_login_is_rejected(self):
        User.objects.create_user(username='regular-user', password='Secure-test-pass-2026')
        response = self.client.post(reverse('login'), {
            'username': 'regular-user', 'password': 'Secure-test-pass-2026',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.session.get('_auth_user_id'))
        self.assertContains(response, 'not permitted')

    def test_staff_can_open_management_pages(self):
        self.client.force_login(self.admin)
        paths = [
            'allocation:dashboard', 'allocation:faculty_list', 'allocation:faculty_add',
            'allocation:faculty_edit', 'allocation:phd_list', 'allocation:phd_add',
            'allocation:phd_edit', 'allocation:classroom_list', 'allocation:classroom_add',
            'allocation:classroom_edit', 'allocation:exam_schedule_list',
            'allocation:exam_schedule_add', 'allocation:exam_schedule_edit',
            'allocation:allocation_result', 'allocation:seating_plan',
            'allocation:ufm_record_list', 'allocation:ufm_record_add',
            'allocation:run_allocation',
        ]
        arguments = {
            'allocation:faculty_edit': self.faculty.pk,
            'allocation:phd_edit': self.phd.pk,
            'allocation:classroom_edit': self.room.pk,
            'allocation:exam_schedule_edit': self.exam.pk,
        }
        for name in paths:
            with self.subTest(url_name=name):
                response = self.client.get(reverse(name, args=[arguments[name]] if name in arguments else None))
                self.assertEqual(response.status_code, 200)

    def test_create_forms_persist_current_model_fields(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('allocation:faculty_add'))
        self.assertContains(response, 'Subject')
        response = self.client.get(reverse('allocation:phd_add'))
        self.assertContains(response, 'Subject')

        response = self.client.post(reverse('allocation:faculty_add'), {
            'name': 'New Faculty', 'email': 'newfaculty@example.test',
            'designation': Faculty.Designation.ASSOCIATE_PROFESSOR,
            'duty_quota': 7, 'subject': self.subject.pk,
        })
        self.assertEqual(response.status_code, 302)
        new_faculty = Faculty.objects.get(email='newfaculty@example.test')
        self.assertEqual(list(new_faculty.subjects.all()), [self.subject])
        response = self.client.post(reverse('allocation:faculty_edit', args=[new_faculty.pk]), {
            'name': 'Updated Faculty', 'email': 'newfaculty@example.test',
            'designation': Faculty.Designation.ASSOCIATE_PROFESSOR,
            'duty_quota': 8, 'subject': self.subject.pk,
        })
        self.assertEqual(response.status_code, 302)
        new_faculty.refresh_from_db()
        self.assertEqual(new_faculty.name, 'Updated Faculty')

        response = self.client.post(reverse('allocation:phd_add'), {
            'name': 'New Scholar', 'email': 'newscholar@example.test',
            'duty_quota': 4, 'subject': self.subject.pk,
        })
        self.assertEqual(response.status_code, 302)
        new_scholar = PhDScholar.objects.get(email='newscholar@example.test')
        self.assertEqual(list(new_scholar.subjects.all()), [self.subject])
        response = self.client.post(reverse('allocation:phd_edit', args=[new_scholar.pk]), {
            'name': 'Updated Scholar', 'email': 'newscholar@example.test',
            'duty_quota': 6, 'subject': self.subject.pk,
        })
        self.assertEqual(response.status_code, 302)
        new_scholar.refresh_from_db()
        self.assertEqual(new_scholar.name, 'Updated Scholar')

        response = self.client.post(reverse('allocation:classroom_add'), {
            'name': 'New Room', 'rows': 8, 'columns': 7,
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Classroom.objects.get(name='New Room').capacity, 56)
        room = Classroom.objects.get(name='New Room')
        response = self.client.post(reverse('allocation:classroom_edit', args=[room.pk]), {
            'name': 'Updated Room', 'rows': 7, 'columns': 8,
        })
        self.assertEqual(response.status_code, 302)
        room.refresh_from_db()
        self.assertEqual(room.capacity, 56)

        response = self.client.post(reverse('allocation:exam_schedule_add'), {
            'date': '2026-10-11', 'slot': ExamSchedule.Slot.EVENING,
            'examination_type': ExamSchedule.ExaminationType.END_SEMESTER,
            'start_time': '14:00', 'end_time': '17:00',
            'subject': self.subject.pk, 'sections': [self.section.pk],
        })
        self.assertEqual(response.status_code, 302)
        new_exam = ExamSchedule.objects.get(date='2026-10-11')
        self.assertEqual(list(new_exam.exam_sections.values_list('section_id', 'position')), [(self.section.pk, 1)])
        response = self.client.post(reverse('allocation:exam_schedule_edit', args=[new_exam.pk]), {
            'date': '2026-10-12', 'slot': ExamSchedule.Slot.MORNING,
            'examination_type': ExamSchedule.ExaminationType.END_SEMESTER,
            'start_time': '10:00', 'end_time': '12:00',
            'subject': self.subject.pk, 'sections': [self.section.pk],
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ExamSchedule.objects.filter(pk=new_exam.pk, date='2026-10-12').exists())

        response = self.client.post(reverse('allocation:ufm_record_add'), {
            'faculty': self.faculty.pk, 'phd_scholar': '',
            'exam_schedule': self.exam.pk, 'count': 1, 'notes': 'Smoke test',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(UFMRecord.objects.filter(faculty=self.faculty).exists())

    def test_seating_generation_and_downloads(self):
        self.client.force_login(self.admin)
        Student.objects.create(name='Student One', roll_no=1, section=self.section)
        Student.objects.create(name='Student Two', roll_no=2, section=self.section)
        response = self.client.post(reverse('allocation:generate_seating'), {
            'exam_id': self.exam.pk, 'classrooms': [self.room.pk], 'fill_order': 'column',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Seating.objects.filter(exam_schedule=self.exam).count(), 2)

        csv_response = self.client.get(reverse('allocation:seating_plan_csv', args=[self.exam.pk]))
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn(b'Roll No,Room,Seat No,Row,Column', csv_response.content)
        self.assertNotIn(b'Student Name', csv_response.content)
        pdf_response = self.client.get(reverse('allocation:seating_plan_pdf', args=[self.exam.pk]))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertTrue(pdf_response.content.startswith(b'%PDF-'))

    def test_official_duty_order_is_room_wise_and_filters_by_date_and_shift(self):
        self.client.force_login(self.admin)
        room_two = Classroom.objects.create(name='Test Room 2', rows=5, columns=6)
        DutyAllocation.objects.create(exam_schedule=self.exam, classroom=self.room,
            faculty=self.faculty, subject=self.subject, is_subject_coordinator=True,
            role_type=DutyAllocation.RoleType.PROFESSOR)
        DutyAllocation.objects.create(exam_schedule=self.exam, classroom=self.room,
            phd_scholar=self.phd, role_type=DutyAllocation.RoleType.PHD_SCHOLAR)
        identified_scholar = PhDScholar.objects.create(name='Identified Scholar', scholar_id='PHD-006')
        DutyAllocation.objects.create(exam_schedule=self.exam, classroom=self.room,
            phd_scholar=identified_scholar, role_type=DutyAllocation.RoleType.PHD_SCHOLAR)
        second_exam = ExamSchedule.objects.create(date='2026-10-11', slot=ExamSchedule.Slot.EVENING,
            start_time='14:00', end_time='17:00', subject=self.subject)
        DutyAllocation.objects.create(exam_schedule=second_exam, classroom=room_two,
            faculty=self.faculty, role_type=DutyAllocation.RoleType.PROFESSOR)
        exam_session = ExamSession.objects.create(name='Autumn Final Examination')
        self.exam.session = exam_session
        self.exam.save(update_fields=['session'])

        full = self.client.get(reverse('allocation:duty_order_pdf'))
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full['Content-Type'], 'application/pdf')
        full_text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(full.content)).pages)
        self.assertIn('Deployment Test Subject', full_text)
        self.assertIn('Test Faculty (duty: Test Room)', full_text)
        self.assertIn('B.Tech. End Semester Examination Duty Chart, October 2026', full_text)
        self.assertIn('Test Room', full_text)
        self.assertIn('PhD Scholars', full_text)
        self.assertIn('Test Faculty', full_text)
        self.assertIn('PHD - Test Scholar', full_text)
        self.assertIn('PHD-006', full_text)
        self.assertIn('Test Room 2', full_text)
        day = self.client.get(reverse('allocation:duty_order_pdf'), {'date': '2026-10-10'})
        day_text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(day.content)).pages)
        self.assertIn('PHD - Test Scholar', day_text)
        self.assertNotIn('Test Room 2', day_text)
        shift = self.client.get(reverse('allocation:duty_order_pdf'), {'slot': ExamSchedule.Slot.EVENING})
        shift_text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(shift.content)).pages)
        self.assertIn('Test Room 2', shift_text)
        self.assertNotIn('PHD - Test Scholar', shift_text)
        session = self.client.get(reverse('allocation:duty_order_pdf'), {'session': exam_session.pk})
        session_text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(session.content)).pages)
        self.assertIn('PHD - Test Scholar', session_text)
        self.assertNotIn('Test Room 2', session_text)

    def test_mid_and_end_chart_selection_uses_schedule_type_and_previews_inline(self):
        self.client.force_login(self.admin)
        mid_faculty = Faculty.objects.create(name='Mid Term Faculty',
            designation=Faculty.Designation.ASSOCIATE_PROFESSOR)
        mid_exam = ExamSchedule.objects.create(date='2026-09-21', slot=ExamSchedule.Slot.MORNING,
            examination_type=ExamSchedule.ExaminationType.MID_SEMESTER,
            start_time='09:00', end_time='12:00', instructions='Carry your institute ID.')
        DutyAllocation.objects.create(exam_schedule=mid_exam, classroom=self.room,
            faculty=mid_faculty, role_type=DutyAllocation.RoleType.PROFESSOR)
        end_response = self.client.get(reverse('allocation:duty_order_pdf'), {'type': 'END'})
        end_text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(end_response.content)).pages)
        self.assertIn('B.Tech. End Semester Examination Duty Chart', end_text)
        self.assertNotIn('Mid Term Faculty', end_text)
        mid_response = self.client.get(reverse('allocation:duty_order_pdf'), {'type': 'MID', 'preview': '1'})
        mid_text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(mid_response.content)).pages)
        self.assertEqual(mid_response['Content-Disposition'].split(';')[0], 'inline')
        self.assertIn('B.Tech. Mid Semester Examination Duty Chart, September 2026', mid_text)
        self.assertIn('Mid Term Faculty', mid_text)
        self.assertIn('Carry your institute ID.', mid_text)
        self.assertIn('Exam Coordinator(s)', mid_text)

    def test_empty_semester_chart_has_clear_single_page_empty_state(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('allocation:duty_order_pdf'), {'type': 'MID'})
        pages = PdfReader(io.BytesIO(response.content)).pages
        self.assertEqual(len(pages), 1)
        text = pages[0].extract_text() or ''
        self.assertIn('B.Tech. Mid Semester Examination Duty Chart', text)
        self.assertIn('No finalized assignments for this examination type.', text)

    def test_individual_faculty_details_include_each_current_assignment(self):
        self.client.force_login(self.admin)
        DutyAllocation.objects.create(exam_schedule=self.exam, classroom=self.room,
            faculty=self.faculty, role_type=DutyAllocation.RoleType.PROFESSOR)
        response = self.client.get(reverse('allocation:faculty_duty_details_pdf'),
            {'faculty_id': self.faculty.pk, 'preview': '1'})
        text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(response.content)).pages)
        self.assertEqual(response['Content-Disposition'].split(';')[0], 'inline')
        self.assertIn('Test Faculty', text)
        self.assertIn('Test Room', text)

    def test_duty_slip_uses_current_replacement_assignment(self):
        self.client.force_login(self.admin)
        replacement = Faculty.objects.create(name='Current Replacement', email='current@example.test',
            designation=Faculty.Designation.ASSISTANT_PROFESSOR)
        allocation = DutyAllocation.objects.create(exam_schedule=self.exam, classroom=self.room,
            faculty=replacement, role_type=DutyAllocation.RoleType.ASSISTANT_PROFESSOR)
        response = self.client.get(reverse('allocation:duty_slip_pdf'), {
            'allocation': allocation.pk, 'person_type': 'faculty',
        })
        text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(response.content)).pages)
        self.assertIn('Current Replacement', text)
        self.assertNotIn('Test Faculty', text)
        scholar_allocation = DutyAllocation.objects.create(exam_schedule=self.exam,
            classroom=self.room, phd_scholar=self.phd,
            role_type=DutyAllocation.RoleType.PHD_SCHOLAR)
        scholar_response = self.client.get(reverse('allocation:duty_slip_pdf'), {
            'allocation': scholar_allocation.pk, 'person_type': 'phd',
        })
        scholar_text = '\n'.join(page.extract_text() or '' for page in
            PdfReader(io.BytesIO(scholar_response.content)).pages)
        self.assertIn('PHD - Test Scholar', scholar_text)
        self.assertNotIn('Research Scholar', scholar_text)

    def test_large_room_table_continues_across_pages_with_headers(self):
        self.client.force_login(self.admin)
        DutyAllocation.objects.create(exam_schedule=self.exam, classroom=self.room,
            faculty=self.faculty, role_type=DutyAllocation.RoleType.PROFESSOR)
        for index in range(70):
            person = Faculty.objects.create(name=f'Long List Faculty {index:02d}',
                designation=Faculty.Designation.ASSISTANT_PROFESSOR)
            DutyAllocation.objects.create(exam_schedule=self.exam, classroom=self.room,
                faculty=person, role_type=DutyAllocation.RoleType.ASSISTANT_PROFESSOR)
        response = self.client.get(reverse('allocation:duty_order_pdf'))
        pages = PdfReader(io.BytesIO(response.content)).pages
        self.assertGreater(len(pages), 1)
        all_text = '\n'.join(page.extract_text() or '' for page in pages)
        self.assertIn('Long List Faculty 00', all_text)
        self.assertIn('Long List Faculty 69', all_text)
        self.assertIn('Page 2', all_text)
        self.assertGreaterEqual(all_text.count('PhD Scholars'), 2)

    def test_allocator_respects_date_time_unavailability_and_timetable(self):
        Availability.objects.create(faculty=self.faculty, date=self.exam.date,
            start_time='09:30', end_time='10:30', is_available=False)
        exam_date = date.fromisoformat(str(self.exam.date))
        TimetableEntry.objects.create(phd_scholar=self.phd, weekday=exam_date.weekday(),
            start_time='09:00', end_time='10:00', label='Teaching')
        engine = AllocationEngine()
        faculty_candidate = engine.professors[self.faculty.pk]
        phd_candidate = engine.phds[self.phd.pk]
        self.assertFalse(faculty_candidate.can_take(exam_date, self.exam.slot, time(9, 0), time(12, 0)))
        self.assertFalse(phd_candidate.can_take(exam_date, self.exam.slot, time(9, 0), time(12, 0)))

    def test_session_seating_includes_minor_elective_once_and_roll_only(self):
        session = ExamSession.objects.create(name='Fall term')
        self.exam.session = session
        self.exam.save(update_fields=['session'])
        self.exam.subject = self.subject
        self.exam.save(update_fields=['subject'])
        minor_section = Section.objects.create(name='CSE-Minor')
        elective_section = Section.objects.create(name='ECE-Elective')
        regular = Student.objects.create(name='Private Name', roll_no=4, section=self.section)
        minor = Student.objects.create(name='Private Minor', roll_no=2, section=minor_section, category=Student.Category.MINOR)
        elective = Student.objects.create(name='Private Elective', roll_no=3, section=elective_section, category=Student.Category.ELECTIVE)
        StudentSubjectRegistration.objects.create(student=minor, subject=self.subject, category='MINOR')
        StudentSubjectRegistration.objects.create(student=elective, subject=self.subject, category='ELECTIVE')
        # The same student registered under two paths remains one seat assignment.
        StudentSubjectRegistration.objects.create(student=regular, subject=self.subject, category='ELECTIVE')
        self.client.force_login(self.admin)
        response = self.client.post(reverse('allocation:generate_session_seating'), {
            'session_id': session.pk, 'classrooms': [self.room.pk], 'fill_order': 'row',
        })
        self.assertEqual(response.status_code, 302)
        seats = list(SessionSeating.objects.filter(session=session).select_related('student').order_by('seat_no'))
        self.assertEqual([seat.student.roll_no for seat in seats], [4, 2, 3])
        export = self.client.get(reverse('allocation:session_seating_csv', args=[session.pk]))
        self.assertIn(b'Roll No,Room,Seat No,Row,Column', export.content)
        self.assertNotIn(b'Private Name', export.content)

    def test_replacement_acceptance_updates_duty_and_notifies_admin(self):
        from django.contrib.auth.models import User
        original_user = User.objects.create_user('original-profile', password='Temp-secure-password-42')
        target_user = User.objects.create_user('target-profile', password='Temp-secure-password-43')
        self.faculty.user = original_user
        self.faculty.save(update_fields=['user'])
        target = Faculty.objects.create(name='Replacement Faculty', email='replacement@example.test',
            designation=Faculty.Designation.PROFESSOR, user=target_user)
        allocation = DutyAllocation.objects.create(exam_schedule=self.exam, classroom=self.room,
            faculty=self.faculty, role_type=DutyAllocation.RoleType.PROFESSOR)
        self.client.force_login(original_user)
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse('allocation:replacement_request', args=[allocation.pk]), {
                    'target_faculty': target.pk, 'target_phd_scholar': '',
                })
                self.assertEqual(response.status_code, 302)
                request = ReplacementRequest.objects.get(allocation=allocation)
                self.client.force_login(target_user)
                response = self.client.post(reverse('allocation:replacement_respond', args=[request.pk, 'accept']))
                self.assertEqual(response.status_code, 302)
        allocation.refresh_from_db()
        request.refresh_from_db()
        self.assertEqual(allocation.faculty_id, target.pk)
        self.assertEqual(request.status, ReplacementRequest.Status.ACCEPTED)
        self.assertTrue(Notification.objects.filter(recipient=self.admin, message__icontains='replacement successful').exists())
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(EmailNotification.objects.filter(status=EmailNotification.Status.SENT).count(), 3)

    def test_profile_user_can_update_only_their_own_availability(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user('faculty-login', password='Temp-secure-password-44')
        self.faculty.user = user
        self.faculty.save(update_fields=['user'])
        response = self.client.post(reverse('login'), {
            'username': 'faculty-login', 'password': 'Temp-secure-password-44',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Welcome, Test Faculty')
        response = self.client.post(reverse('allocation:availability'), {
            'date': '2026-10-11', 'start_time': '09:00', 'end_time': '12:00',
            'is_available': 'false', 'note': 'Conference',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Availability.objects.filter(faculty=self.faculty, is_available=False).exists())

    def test_import_preview_then_safe_import_skips_invalid_rows(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile('students.csv',
            b'roll_no,section,name,category\n101,CSE-1,Student One,REGULAR\ninvalid,CSE-1,Student Two,REGULAR\n',
            content_type='text/csv')
        response = self.client.post(reverse('allocation:data_import'), {
            'import_type': 'students', 'data_file': upload,
        })
        self.assertEqual(response.status_code, 302)
        batch = __import__('allocation.models', fromlist=['ImportBatch']).ImportBatch.objects.latest('pk')
        self.assertTrue(batch.rows[0]['errors'] == [])
        self.assertTrue(batch.rows[1]['errors'])
        response = self.client.post(reverse('allocation:data_import_batch', args=[batch.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Student.objects.filter(roll_no=101, section__name='CSE-1').exists())
        self.assertEqual(batch.__class__.objects.get(pk=batch.pk).report['imported'], 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_assignment_email_is_html_logged_and_idempotent(self):
        exam = ExamSchedule.objects.get(pk=self.exam.pk)
        exam.reporting_time = time(8, 45)
        exam.instructions = 'Bring staff identification.'
        exam.save(update_fields=['reporting_time', 'instructions'])
        allocation = DutyAllocation.objects.create(exam_schedule=exam, classroom=self.room,
            faculty=self.faculty, role_type=DutyAllocation.RoleType.PROFESSOR)
        with self.captureOnCommitCallbacks(execute=True):
            queue_duty_assignment(self.faculty, allocation)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.faculty.email])
        self.assertTrue(mail.outbox[0].alternatives)
        self.assertIn('Bring staff identification', mail.outbox[0].alternatives[0][0])
        self.assertEqual(EmailNotification.objects.get().status, EmailNotification.Status.SENT)
        with self.captureOnCommitCallbacks(execute=True):
            queue_duty_assignment(self.faculty, allocation)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailNotification.objects.count(), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_duty_allocation_queues_faculty_and_phd_emails_once(self):
        self.faculty.email = 'professor@example.test'
        self.faculty.save(update_fields=['email'])
        self.faculty.subjects.add(self.subject)
        assistants = [Faculty.objects.create(name=f'Assistant {i}', email=f'assistant{i}@example.test',
            designation=Faculty.Designation.ASSISTANT_PROFESSOR) for i in range(2)]
        scholars = [self.phd] + [PhDScholar.objects.create(name=f'Scholar {i}', email=f'scholar{i}@example.test') for i in range(2)]
        with self.captureOnCommitCallbacks(execute=True):
            allocations = allocate_all_duties()
        self.assertEqual(len(allocations), 6)
        coordinator = [a for a in allocations if a.is_subject_coordinator]
        self.assertEqual(len(coordinator), 1)
        self.assertEqual(coordinator[0].faculty_id, self.faculty.pk)
        self.assertEqual(coordinator[0].subject_id, self.subject.pk)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.coordinator_status, ExamSchedule.CoordinatorStatus.ASSIGNED)
        self.assertEqual(len(mail.outbox), 6)
        self.assertEqual(EmailNotification.objects.filter(notification_type=EmailNotification.Type.DUTY_ASSIGNMENT).count(), 6)
        with self.captureOnCommitCallbacks(execute=True):
            allocate_all_duties()
        self.assertEqual(len(mail.outbox), 6)
        self.assertEqual(EmailNotification.objects.filter(notification_type=EmailNotification.Type.DUTY_ASSIGNMENT).count(), 6)

    def test_missing_coordinator_marks_schedule_unresolved_without_allocating(self):
        self.subject.coordinator = None
        self.subject.save(update_fields=['coordinator'])
        with self.assertRaises(ValidationError):
            allocate_all_duties()
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.coordinator_status, ExamSchedule.CoordinatorStatus.UNRESOLVED)
        self.assertEqual(self.exam.duty_allocations.count(), 0)

    def test_unavailable_coordinator_is_not_replaced(self):
        Availability.objects.create(faculty=self.faculty, date=self.exam.date,
            start_time=time(9), end_time=time(12), is_available=False)
        with self.assertRaises(ValidationError):
            allocate_all_duties()
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.coordinator_status, ExamSchedule.CoordinatorStatus.UNRESOLVED)
        self.assertFalse(self.exam.duty_allocations.filter(is_subject_coordinator=True).exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_failed_email_is_recorded_and_can_be_retried(self):
        with patch('allocation.email_notifications.EmailMultiAlternatives.send', side_effect=RuntimeError('SMTP unavailable')):
            with self.captureOnCommitCallbacks(execute=True):
                queue_person_email(self.faculty,
                    notification_type=EmailNotification.Type.ANNOUNCEMENT,
                    template_key='announcement', subject='Exam office notice',
                    details=[('Announcement', 'A changed reporting instruction.')],
                    idempotency_key='test-failed-email', intro='Please read this notice.')
        item = EmailNotification.objects.get(idempotency_key='test-failed-email')
        self.assertEqual(item.status, EmailNotification.Status.FAILED)
        self.assertIn('SMTP unavailable', item.last_error)
        self.assertEqual(item.attempt_count, 1)
        self.assertTrue(send_queued_email(item.pk))
        item.refresh_from_db()
        self.assertEqual(item.status, EmailNotification.Status.SENT)
        self.assertEqual(item.attempt_count, 2)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_admin_email_history_filters_and_retries_failed_delivery(self):
        with patch('allocation.email_notifications.EmailMultiAlternatives.send', side_effect=RuntimeError('temporary failure')):
            with self.captureOnCommitCallbacks(execute=True):
                queue_person_email(self.faculty,
                    notification_type=EmailNotification.Type.ANNOUNCEMENT,
                    template_key='announcement', subject='Retryable notice',
                    details=[('Announcement', 'Retry test.')],
                    idempotency_key='admin-retry-test', intro='Please review.')
        failed = EmailNotification.objects.get(idempotency_key='admin-retry-test')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('allocation:email_management'), {'q': 'faculty@example.test', 'status': 'FAILED'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Retryable notice')
        response = self.client.post(reverse('allocation:email_retry', args=[failed.pk]))
        self.assertEqual(response.status_code, 302)
        failed.refresh_from_db()
        self.assertEqual(failed.status, EmailNotification.Status.SENT)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_schedule_change_emails_affected_person_with_old_and_new_details(self):
        self.faculty.email = 'faculty-schedule@example.test'
        self.faculty.save(update_fields=['email'])
        DutyAllocation.objects.create(exam_schedule=self.exam, classroom=self.room,
            faculty=self.faculty, role_type=DutyAllocation.RoleType.PROFESSOR)
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('allocation:exam_schedule_edit', args=[self.exam.pk]), {
                'date': '2026-10-11', 'slot': ExamSchedule.Slot.MORNING,
                'examination_type': ExamSchedule.ExaminationType.END_SEMESTER,
                'start_time': '10:00', 'end_time': '13:00', 'reporting_time': '09:45',
                'instructions': 'Use the north entrance.', 'subject': self.subject.pk,
                'session': '', 'sections': [self.section.pk],
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('09:00', mail.outbox[0].body)
        self.assertIn('10:00', mail.outbox[0].body)
        self.assertEqual(EmailNotification.objects.get().notification_type, EmailNotification.Type.SCHEDULE_UPDATE)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_announcement_email_is_sent_only_to_selected_people(self):
        from django.contrib.auth.models import User
        self.faculty.email = 'selected@example.test'
        self.faculty.save(update_fields=['email'])
        other = Faculty.objects.create(name='Not Selected', email='not-selected@example.test',
            designation=Faculty.Designation.PROFESSOR)
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('allocation:announcement_add'), {
                'message': 'Check the revised examination reporting time.',
                'faculty': [self.faculty.pk], 'phd_scholars': [],
            })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['selected@example.test'])
        self.assertFalse(EmailNotification.objects.filter(recipient_email=other.email).exists())
