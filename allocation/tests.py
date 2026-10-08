import io

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from .models import (
    Classroom, ExamSchedule, ExamSection, Faculty, PhDScholar, Section, Seating,
    Student, Subject, UFMRecord,
)

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
            'start_time': '14:00', 'end_time': '17:00',
            'subject': self.subject.pk, 'sections': [self.section.pk],
        })
        self.assertEqual(response.status_code, 302)
        new_exam = ExamSchedule.objects.get(date='2026-10-11')
        self.assertEqual(list(new_exam.exam_sections.values_list('section_id', 'position')), [(self.section.pk, 1)])
        response = self.client.post(reverse('allocation:exam_schedule_edit', args=[new_exam.pk]), {
            'date': '2026-10-12', 'slot': ExamSchedule.Slot.MORNING,
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
        self.assertIn(b'Section,Roll No,Student Name,Room,Seat No,Row,Column', csv_response.content)
        pdf_response = self.client.get(reverse('allocation:seating_plan_pdf', args=[self.exam.pk]))
        self.assertEqual(pdf_response.status_code, 200)
        self.assertTrue(pdf_response.content.startswith(b'%PDF-'))
