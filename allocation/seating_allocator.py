"""Pure classroom seating allocation helpers."""
from dataclasses import dataclass
from typing import Iterable, Literal


FillOrder = Literal['row', 'column']


class InsufficientCapacityError(ValueError):
    pass


@dataclass(frozen=True)
class StudentInput:
    roll_no: int
    section_id: int
    section_name: str


@dataclass(frozen=True)
class RoomInput:
    id: int
    name: str
    rows: int
    columns: int

    @property
    def capacity(self) -> int:
        return self.rows * self.columns


@dataclass(frozen=True)
class SeatAssignment:
    student: StudentInput
    room_id: int
    room_name: str
    seat_no: int
    row_no: int
    col_no: int


def _positions(room: RoomInput, fill_order: FillOrder):
    if fill_order == 'column':
        return [(row, column) for column in range(1, room.columns + 1)
                for row in range(1, room.rows + 1)]
    return [(row, column) for row in range(1, room.rows + 1)
            for column in range(1, room.columns + 1)]


def allocate_seats(
    sections: Iterable[tuple[int, str, Iterable[StudentInput]]],
    rooms: Iterable[RoomInput],
    fill_order: FillOrder = 'row',
) -> list[SeatAssignment]:
    """Allocate ordered sections through ordered rooms without database access."""
    rooms = list(rooms)
    if fill_order not in ('row', 'column'):
        raise ValueError('Fill order must be row or column.')
    if any(room.rows < 1 or room.columns < 1 for room in rooms):
        raise ValueError('Classroom rows and columns must be positive integers.')

    ordered_students = []
    for section_id, section_name, students in sections:
        ordered_students.extend(sorted(students, key=lambda student: student.roll_no))
    if len(ordered_students) > sum(room.capacity for room in rooms):
        raise InsufficientCapacityError('Insufficient classroom seats for the selected students.')

    assignments = []
    student_index = 0
    for room in rooms:
        for seat_no, (row_no, col_no) in enumerate(_positions(room, fill_order), start=1):
            if student_index == len(ordered_students):
                return assignments
            student = ordered_students[student_index]
            assignments.append(SeatAssignment(
                student=student, room_id=room.id, room_name=room.name,
                seat_no=seat_no, row_no=row_no, col_no=col_no,
            ))
            student_index += 1
    return assignments


def contiguous_ranges(assignments: Iterable[SeatAssignment]):
    """Return contiguous roll-number ranges for each (section, room) run."""
    ranges = []
    current = None
    for assignment in assignments:
        key = (assignment.student.section_id, assignment.room_id)
        if (current is None or current['key'] != key or
                assignment.student.roll_no != current['to_roll_no'] + 1):
            if current:
                ranges.append(current)
            current = {
                'key': key,
                'section_id': assignment.student.section_id,
                'room_id': assignment.room_id,
                'from_roll_no': assignment.student.roll_no,
                'to_roll_no': assignment.student.roll_no,
            }
        else:
            current['to_roll_no'] = assignment.student.roll_no
    if current:
        ranges.append(current)
    return ranges
