"""Pure subject-faculty selection policy for duty allocation."""


def choose_faculty_with_subject_rule(candidate_ids, subject_faculty_ids, needed):
    """Prefer non-subject faculty; only use subject faculty to fill a shortfall."""
    candidate_ids = list(candidate_ids)
    subject_faculty_ids = set(subject_faculty_ids)
    normal = [faculty_id for faculty_id in candidate_ids if faculty_id not in subject_faculty_ids]
    compulsory = [faculty_id for faculty_id in candidate_ids if faculty_id in subject_faculty_ids]
    selected = normal[:needed]
    selected.extend(compulsory[:max(0, needed - len(selected))])
    return [(faculty_id, faculty_id in subject_faculty_ids) for faculty_id in selected]
