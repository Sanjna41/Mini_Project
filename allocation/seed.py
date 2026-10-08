from allocation.models import Classroom, Faculty, PhDScholar


def run():
    """Create repeatable local sample records using the current model fields."""
    for number in range(1, 11):
        Faculty.objects.get_or_create(
            email=f'faculty{number}@example.test',
            defaults={
                'name': f'Faculty Member {number}',
                'designation': Faculty.Designation.PROFESSOR,
                'duty_quota': 5,
            },
        )

    for number in range(1, 16):
        PhDScholar.objects.get_or_create(
            email=f'phd{number}@example.test',
            defaults={
                'name': f'PhD Scholar {number}',
                'duty_quota': 3,
            },
        )

    for number in range(1, 6):
        Classroom.objects.get_or_create(
            name=f'Room-{number}',
            defaults={'rows': 6, 'columns': 10},
        )
