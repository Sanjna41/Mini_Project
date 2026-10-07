from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse

from .models import DutyAllocation, Faculty


def send_allocation_emails(request) -> None:
    """Send simple text emails to each faculty with their duties."""
    base_url = request.build_absolute_uri('/')[:-1]
    for faculty in Faculty.objects.exclude(email=''):
        duties = DutyAllocation.objects.filter(
            faculty=faculty
        ).select_related('exam_schedule', 'classroom')
        if not duties.exists():
            continue

        url = base_url + reverse('allocation:allocation_result')
        lines: list[str] = [
            f"Dear {faculty.name},",
            "",
            "Your exam invigilation duties are as follows:",
            "",
            *[
                f"- {d.exam_schedule.date} "
                f"{d.exam_schedule.get_slot_display()} | "
                f"Room {d.classroom.name} | {d.get_role_type_display()}"
                for d in duties
            ],
            "",
            f"Full allocation details: {url}",
        ]

        send_mail(
            subject="Exam Invigilation Duty Allocation",
            message="\n".join(lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[faculty.email],
            fail_silently=True,
        )

