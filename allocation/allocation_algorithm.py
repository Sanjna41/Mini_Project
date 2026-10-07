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
)

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

    def can_take(self, date, slot) -> bool:
        if (date, slot) in self.occupied_slots:
            return False
        last = self.last_slot_by_date.get(date)
        if last is not None and last != slot:
            return False
        if self.today_duties + self.prev_duties >= self.quota:
            return False
        return True

    def register(self, date, slot) -> None:
        self.occupied_slots.add((date, slot))
        self.last_slot_by_date[date] = slot
        self.today_duties += 1

    @property
    def selection_weight(self) -> float:
        base = 1.0 / (1.0 + self.prev_duties + self.ufm_count)
        return base * (0.9 + 0.2 * random.random())


class AllocationEngine:
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
    ) -> List[StaffCandidate]:
        chosen: List[StaffCandidate] = []
        available = [cid for cid in ids_order if candidates[cid].can_take(date, slot)]
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

    @transaction.atomic
    def allocate(self) -> List[DutyAllocation]:
        DutyAllocation.objects.all().delete()
        schedules = list(ExamSchedule.objects.all())
        rooms = list(Classroom.objects.all().order_by('name'))
        if not schedules or not rooms:
            return []

        created: List[DutyAllocation] = []

        for s in schedules:
            date = s.date
            slot = s.slot

            coordinator = None
            coordinator_pool = None
            if s.subject_id:
                coordinator_candidates = list(
                    Faculty.objects.filter(subjects=s.subject).order_by('name')
                )
                if not coordinator_candidates:
                    raise ValidationError(
                        f"No subject coordinator is assigned to {s.subject} "
                        f"({date}). Add a faculty member to that subject before allocating duties."
                    )
                coordinator = next(
                    (f for f in coordinator_candidates
                     if (self.assistants if f.designation == Faculty.Designation.ASSISTANT_PROFESSOR
                         else self.professors)[f.id].can_take(date, slot)),
                    None,
                )
                if coordinator is None:
                    raise ValidationError(
                        f"No available subject coordinator for {s.subject} on {date} ({slot})."
                )
                if coordinator.designation == Faculty.Designation.ASSISTANT_PROFESSOR:
                    coordinator_pool = self.assistants
                else:
                    coordinator_pool = self.professors
                coordinator_pool[coordinator.id].register(date, slot)

            for room_index, room in enumerate(rooms):
                profs = self._weighted_pick(
                    self.professors, self._prof_ids, date, slot,
                    PROFESSORS_PER_ROOM - int(
                        room_index == 0 and coordinator_pool is self.professors
                    ),
                )
                assts = self._weighted_pick(
                    self.assistants, self._asst_ids, date, slot,
                    ASSISTANTS_PER_ROOM - int(
                        room_index == 0 and coordinator_pool is self.assistants
                    ),
                )
                phds = self._weighted_pick(
                    self.phds, self._phd_ids, date, slot, PHDS_PER_ROOM
                )

                for p in profs:
                    created.append(
                        DutyAllocation(
                            exam_schedule=s,
                            classroom=room,
                            faculty_id=p.id,
                            role_type=DutyAllocation.RoleType.PROFESSOR,
                        )
                    )
                if room_index == 0 and coordinator_pool is self.professors:
                    created.append(DutyAllocation(
                        exam_schedule=s, classroom=room, faculty_id=coordinator.id,
                        role_type=(DutyAllocation.RoleType.ASSISTANT_PROFESSOR
                                   if coordinator.designation == Faculty.Designation.ASSISTANT_PROFESSOR
                                   else DutyAllocation.RoleType.PROFESSOR),
                    ))
                if room_index == 0 and coordinator_pool is self.assistants:
                    created.append(DutyAllocation(
                        exam_schedule=s, classroom=room, faculty_id=coordinator.id,
                        role_type=DutyAllocation.RoleType.ASSISTANT_PROFESSOR,
                    ))
                for a in assts:
                    created.append(
                        DutyAllocation(
                            exam_schedule=s,
                            classroom=room,
                            faculty_id=a.id,
                            role_type=DutyAllocation.RoleType.ASSISTANT_PROFESSOR,
                        )
                    )
                for ph in phds:
                    created.append(
                        DutyAllocation(
                            exam_schedule=s,
                            classroom=room,
                            phd_scholar_id=ph.id,
                            role_type=DutyAllocation.RoleType.PHD_SCHOLAR,
                        )
                    )

        DutyAllocation.objects.bulk_create(created)
        return created


def allocate_all_duties(clear_existing: bool = True) -> List[DutyAllocation]:
    engine = AllocationEngine()
    return engine.allocate()

