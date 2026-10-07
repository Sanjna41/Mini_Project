import io

from django.test import SimpleTestCase

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
