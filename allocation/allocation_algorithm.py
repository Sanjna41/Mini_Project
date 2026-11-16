import random
from dataclasses import dataclass, field
from typing import List, Dict, Tuple

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    Faculty,
    PhDScholar,
    Classroom,
    ExamSchedule,
    DutyAllocation,
    UFMRecord,
    Availability,
    TimetableEntry,
    Notification,
)
from .email_notifications import queue_duty_assignment
from .email_notifications import queue_person_email, duty_email_details

PROFESSORS_PER_ROOM = 1
ASSISTANTS_PER_ROOM = 2
PHDS_PER_ROOM = 3


@dataclass
class StaffCandidate:
    id: int
    quota: int
    prev_duties: int = 0
    ufm_count: int = 0
    today_duties: int = 0
    occupied_slots: set = field(default_factory=set)
    last_slot_by_date: Dict = field(default_factory=dict)
    unavailable_intervals: list = field(default_factory=list)
    class_intervals: list = field(default_factory=list)

    def can_take(self, date, slot, start_time=None, end_time=None) -> bool:
        return self.conflict_reason(date, slot, start_time, end_time) is None

    def conflict_reason(self, date, slot, start_time=None, end_time=None):
        if (date, slot) in self.occupied_slots:
            return 'already has a duty in this shift'
        last = self.last_slot_by_date.get(date)
        if last is not None and last != slot:
            return 'already has a duty in another shift on this date'
        if self.today_duties + self.prev_duties >= self.quota:
            return 'has reached the duty quota'
        if start_time is not None and end_time is not None:
            if any(d == date and a < end_time and b > start_time for d, a, b in self.unavailable_intervals):
                return 'is unavailable during the examination time'
            if any(day == date.weekday() and a < end_time and b > start_time
                   for day, a, b in self.class_intervals):
                return 'has a timetable conflict during the examination time'
        return None

    def register(self, date, slot) -> None:
        self.occupied_slots.add((date, slot))
        self.last_slot_by_date[date] = slot
        self.today_duties += 1

    @property
    def selection_weight(self) -> float:
        base = 1.0 / (1.0 + self.prev_duties + self.ufm_count)
        return base * (0.9 + 0.2 * random.random())


class _AllocationEngineBase:
    def __init__(self) -> None:
        self.professors: Dict[int, StaffCandidate] = {}
        self.assistants: Dict[int, StaffCandidate] = {}
        self.phds: Dict[int, StaffCandidate] = {}
        self._init_pools()

    def _init_pools(self) -> None:
        faculty_ufm, phd_ufm = self._build_ufm_scores()
        prev_fac_duties, prev_phd_duties = self._build_previous_duty_counts()

        for f in Faculty.objects.all():
            prev = prev_fac_duties.get(f.id, 0)
            ufm = faculty_ufm.get(f.id, 0)
            c = StaffCandidate(
                id=f.id,
                quota=f.duty_quota,
                prev_duties=prev,
                ufm_count=ufm,
                unavailable_intervals=[(a.date, a.start_time, a.end_time) for a in Availability.objects.filter(faculty=f, is_available=False)],
                class_intervals=[(t.weekday, t.start_time, t.end_time) for t in TimetableEntry.objects.filter(faculty=f)],
            )
            if f.designation == Faculty.Designation.ASSISTANT_PROFESSOR:
                self.assistants[f.id] = c
            else:
                self.professors[f.id] = c

        for p in PhDScholar.objects.all():
            prev = prev_phd_duties.get(p.id, 0)
            ufm = phd_ufm.get(p.id, 0)
            self.phds[p.id] = StaffCandidate(
                id=p.id,
                quota=p.duty_quota,
                prev_duties=prev,
                ufm_count=ufm,
                unavailable_intervals=[(a.date, a.start_time, a.end_time) for a in Availability.objects.filter(phd_scholar=p, is_available=False)],
                class_intervals=[(t.weekday, t.start_time, t.end_time) for t in TimetableEntry.objects.filter(phd_scholar=p)],
            )

        self._prof_ids = list(self.professors.keys())
        self._asst_ids = list(self.assistants.keys())
        self._phd_ids = list(self.phds.keys())
        random.shuffle(self._prof_ids)
        random.shuffle(self._asst_ids)
        random.shuffle(self._phd_ids)

    @staticmethod
    def _build_ufm_scores() -> Tuple[Dict[int, int], Dict[int, int]]:
        fac_scores: Dict[int, int] = {}
        phd_scores: Dict[int, int] = {}
        for r in UFMRecord.objects.all():
            if r.faculty_id:
                fac_scores[r.faculty_id] = fac_scores.get(r.faculty_id, 0) + r.count
            if r.phd_scholar_id:
                phd_scores[r.phd_scholar_id] = phd_scores.get(r.phd_scholar_id, 0) + r.count
        return fac_scores, phd_scores

    @staticmethod
    def _build_previous_duty_counts() -> Tuple[Dict[int, int], Dict[int, int]]:
        fac_counts: Dict[int, int] = {}
        phd_counts: Dict[int, int] = {}
        for d in DutyAllocation.objects.select_related('exam_schedule'):
            if d.faculty_id:
                fac_counts[d.faculty_id] = fac_counts.get(d.faculty_id, 0) + 1
            if d.phd_scholar_id:
                phd_counts[d.phd_scholar_id] = phd_counts.get(d.phd_scholar_id, 0) + 1
        return fac_counts, phd_counts

    def _weighted_pick(
        self,
        candidates: Dict[int, StaffCandidate],
        ids_order: List[int],
        date,
        slot,
        needed: int,
        start_time=None,
        end_time=None,
    ) -> List[StaffCandidate]:
        chosen: List[StaffCandidate] = []
        available = [cid for cid in ids_order if candidates[cid].can_take(date, slot, start_time, end_time)]
        if len(available) < needed:
            raise ValidationError(
                f"Insufficient staff on {date} slot {slot}. "
                f"Required {needed}, available {len(available)}."
            )
        pool = available[:]
        while len(chosen) < needed:
            weights = [candidates[cid].selection_weight for cid in pool]
            total = sum(weights) or float(len(pool))
            r = random.uniform(0, total)
            upto = 0.0
            for idx, cid in enumerate(pool):
                w = weights[idx] or (total / len(pool))
                upto += w
                if upto >= r:
                    chosen.append(candidates[cid])
                    pool.pop(idx)
                    break
        for c in chosen:
            c.register(date, slot)
        return chosen


class CoordinatorAllocationError(ValidationError):
    def __init__(self, message, schedule_ids):
        super().__init__(message)
        self.schedule_ids = list(schedule_ids)


class AllocationEngine(_AllocationEngineBase):
    @transaction.atomic
    def allocate(self) -> List[DutyAllocation]:
        previous_allocations = list(DutyAllocation.objects.select_related(
            'exam_schedule', 'classroom', 'faculty', 'phd_scholar'
        ))
        previous_people = {}
        previous_keys = set()
        for old in previous_allocations:
            person = old.faculty or old.phd_scholar
            if not person:
                continue
            person_key = ('faculty', old.faculty_id) if old.faculty_id else ('phd', old.phd_scholar_id)
            key = (old.exam_schedule_id, old.classroom_id, old.role_type, person_key)
            previous_keys.add(key)
            previous_people[key] = (person, old)
        schedules = list(ExamSchedule.objects.select_related(
            'subject', 'subject__coordinator'
        ).order_by('date', 'start_time', 'slot', 'pk'))
        rooms = list(Classroom.objects.all().order_by('name'))
        if not schedules or not rooms:
            return []

        missing = [s for s in schedules if s.subject_id and not s.subject.coordinator_id]
        if missing:
            details = '; '.join(f'{s.subject.name} on {s.date} ({s.get_slot_display()})'
                                for s in missing)
            raise CoordinatorAllocationError(
                'Subject coordinator assignment is unresolved for: ' + details +
                '. Assign a coordinator to each subject before running allocation.',
                [s.pk for s in missing],
            )

        DutyAllocation.objects.all().delete()
        coordinator_by_schedule = {}
        coordinator_pool_by_schedule = {}
        # Reserve every coordinator before random room staffing so another
        # subject cannot consume their slot first.
        for schedule in schedules:
            if not schedule.subject_id:
                continue
            coordinator = schedule.subject.coordinator
            pool = (self.assistants if coordinator.designation == Faculty.Designation.ASSISTANT_PROFESSOR
                    else self.professors)
            candidate = pool[coordinator.pk]
            reason = candidate.conflict_reason(
                schedule.date, schedule.slot, schedule.start_time, schedule.end_time
            )
            if reason:
                raise CoordinatorAllocationError(
                    f'Subject coordinator {coordinator.name} for {schedule.subject.name} '
                    f'on {schedule.date} ({schedule.get_slot_display()}) cannot be assigned: {reason}. '
                    'This schedule remains unresolved; resolve the conflict and run allocation again.',
                    [schedule.pk],
                )
            candidate.register(schedule.date, schedule.slot)
            coordinator_by_schedule[schedule.pk] = coordinator
            coordinator_pool_by_schedule[schedule.pk] = pool

        created: List[DutyAllocation] = []

        for s in schedules:
            date = s.date
            slot = s.slot
            start_time, end_time = s.start_time, s.end_time

            coordinator = coordinator_by_schedule.get(s.pk)
            coordinator_pool = coordinator_pool_by_schedule.get(s.pk)

            for room_index, room in enumerate(rooms):
                profs = self._weighted_pick(
                    self.professors, self._prof_ids, date, slot,
                    PROFESSORS_PER_ROOM - int(
                        room_index == 0 and coordinator_pool is self.professors
                    ),
                    start_time, end_time,
                )
                assts = self._weighted_pick(
                    self.assistants, self._asst_ids, date, slot,
                    ASSISTANTS_PER_ROOM - int(
                        room_index == 0 and coordinator_pool is self.assistants
                    ),
                    start_time, end_time,
                )
                phds = self._weighted_pick(
                    self.phds, self._phd_ids, date, slot, PHDS_PER_ROOM, start_time, end_time
                )

                for p in profs:
                    created.append(
                        DutyAllocation(
                            exam_schedule=s,
                            classroom=room,
                            faculty_id=p.id,
                            subject=s.subject,
                            role_type=DutyAllocation.RoleType.PROFESSOR,
                        )
                    )
                if room_index == 0 and coordinator_pool is self.professors:
                    created.append(DutyAllocation(
                        exam_schedule=s, classroom=room, faculty_id=coordinator.id,
                        subject=s.subject, is_subject_coordinator=True,
                        role_type=(DutyAllocation.RoleType.ASSISTANT_PROFESSOR
                                   if coordinator.designation == Faculty.Designation.ASSISTANT_PROFESSOR
                                   else DutyAllocation.RoleType.PROFESSOR),
                    ))
                if room_index == 0 and coordinator_pool is self.assistants:
                    created.append(DutyAllocation(
                        exam_schedule=s, classroom=room, faculty_id=coordinator.id,
                        subject=s.subject, is_subject_coordinator=True,
                        role_type=DutyAllocation.RoleType.ASSISTANT_PROFESSOR,
                    ))
                for a in assts:
                    created.append(
                        DutyAllocation(
                            exam_schedule=s,
                            classroom=room,
                            faculty_id=a.id,
                            subject=s.subject,
                            role_type=DutyAllocation.RoleType.ASSISTANT_PROFESSOR,
                        )
                    )
                for ph in phds:
                    created.append(
                        DutyAllocation(
                            exam_schedule=s,
                            classroom=room,
                            phd_scholar_id=ph.id,
                            subject=s.subject,
                            role_type=DutyAllocation.RoleType.PHD_SCHOLAR,
                        )
                    )

        DutyAllocation.objects.bulk_create(created)
        for schedule in schedules:
            schedule.coordinator_status = (
                ExamSchedule.CoordinatorStatus.ASSIGNED if schedule.subject_id
                else ExamSchedule.CoordinatorStatus.NOT_REQUIRED
            )
            schedule.coordinator_note = ''
        ExamSchedule.objects.bulk_update(schedules, ['coordinator_status', 'coordinator_note'])
        current_keys = set()
        by_duty_position = {}
        for allocation in created:
            person = allocation.faculty or allocation.phd_scholar
            person_key = ('faculty', allocation.faculty_id) if allocation.faculty_id else ('phd', allocation.phd_scholar_id)
            key = (allocation.exam_schedule_id, allocation.classroom_id, allocation.role_type, person_key)
            current_keys.add(key)
            by_duty_position.setdefault(key[:3], []).append(person)
            if person and person.user_id:
                Notification.objects.create(
                    recipient_id=person.user_id,
                    message=(f'New exam duty assigned: {allocation.exam_schedule.date} '
                             f'{allocation.exam_schedule.start_time}-{allocation.exam_schedule.end_time}, '
                             f'room {allocation.classroom.name} ({allocation.get_role_type_display()}).'),
                )
            if person:
                queue_duty_assignment(person, allocation)
        for key in previous_keys - current_keys:
            person, old = previous_people[key]
            replacements = by_duty_position.get(key[:3], [])
            details = duty_email_details(old)
            if replacements:
                details.append(('Updated assignment', 'This classroom duty has been reassigned to ' + ', '.join(str(p) for p in replacements) + '.'))
                intro = 'Your examination duty assignment has changed. Review the updated information below.'
            else:
                details.append(('Updated assignment', 'This duty is no longer assigned to you.'))
                intro = 'Your examination duty assignment has changed.'
            queue_person_email(person,
                notification_type='DUTY_ASSIGNMENT', template_key='duty_assignment',
                subject=f'Exam duty assignment updated · {old.exam_schedule.date:%d %b %Y}',
                details=details, idempotency_key=f'duty-change:{old.pk}', intro=intro)
        return created


def allocate_all_duties(clear_existing: bool = True) -> List[DutyAllocation]:
    engine = AllocationEngine()
    try:
        return engine.allocate()
    except CoordinatorAllocationError as exc:
        ExamSchedule.objects.filter(pk__in=exc.schedule_ids).update(
            coordinator_status=ExamSchedule.CoordinatorStatus.UNRESOLVED,
            coordinator_note=str(exc),
        )
        raise

