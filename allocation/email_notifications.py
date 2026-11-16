"""Transactional email outbox and reusable examination email builders."""
import logging
from datetime import datetime, timedelta
from functools import partial

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from .models import EmailNotification

logger = logging.getLogger(__name__)


def queue_email(*, recipient_email, recipient_name, subject, notification_type,
                template_key, details, idempotency_key, recipient=None, intro=None):
    """Persist an email and schedule delivery only after the surrounding commit."""
    if not recipient_email:
        logger.warning('Skipping %s email: recipient has no registered email (key=%s).', notification_type, idempotency_key)
        return None
    try:
        validate_email(recipient_email)
    except Exception:
        logger.warning('Skipping %s email: invalid recipient email (key=%s).', notification_type, idempotency_key)
        return None
    context = {
        'recipient_name': recipient_name or recipient_email,
        'institute_name': getattr(settings, 'INSTITUTE_NAME', 'ExamDutyManager'),
        'heading': subject,
        'intro': intro or '',
        'details': details,
    }
    plain = render_to_string(f'emails/{template_key}.txt', context).strip()
    html = render_to_string(f'emails/{template_key}.html', context)
    message, created = EmailNotification.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            'recipient': recipient, 'recipient_email': recipient_email,
            'recipient_name': recipient_name or '', 'subject': subject,
            'notification_type': notification_type, 'text_body': plain,
            'html_body': html,
        },
    )
    if message.status != EmailNotification.Status.SENT:
        transaction.on_commit(partial(send_queued_email, message.pk))
    return message


def send_queued_email(notification_id):
    """Attempt one outbox item; failures remain visible and can be retried."""
    with transaction.atomic():
        try:
            item = EmailNotification.objects.select_for_update().get(pk=notification_id)
        except EmailNotification.DoesNotExist:
            return False
        if item.status == EmailNotification.Status.SENT:
            return True
        item.status = EmailNotification.Status.PROCESSING
        item.attempt_count += 1
        item.last_attempt_at = timezone.now()
        item.last_error = ''
        item.save(update_fields=['status', 'attempt_count', 'last_attempt_at', 'last_error'])

    try:
        email = EmailMultiAlternatives(
            subject=item.subject,
            body=item.text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[item.recipient_email],
        )
        email.attach_alternative(item.html_body, 'text/html')
        sent = email.send(fail_silently=False)
        if sent != 1:
            raise RuntimeError('Email backend did not confirm delivery.')
    except Exception as exc:
        logger.exception('Email delivery failed (notification_id=%s, type=%s).', item.pk, item.notification_type)
        EmailNotification.objects.filter(pk=item.pk).update(
            status=EmailNotification.Status.FAILED, last_error=str(exc)[:2000]
        )
        return False

    EmailNotification.objects.filter(pk=item.pk).update(
        status=EmailNotification.Status.SENT, sent_at=timezone.now(), last_error=''
    )
    return True


def duty_email_details(allocation):
    exam = allocation.exam_schedule
    reporting = exam.reporting_time
    if reporting is None:
        reporting = (datetime.combine(exam.date, exam.start_time) - timedelta(minutes=10)).time()
    details = [
        ('Examination', exam.session.name if exam.session_id else (str(exam.subject) if exam.subject_id else f'Exam schedule {exam.pk}')),
        ('Date', exam.date.strftime('%d %b %Y')),
        ('Time / shift', f'{exam.get_slot_display()} · {exam.start_time:%H:%M}–{exam.end_time:%H:%M}'),
        ('Room', allocation.classroom.name),
        ('Duty responsibility', allocation.get_role_type_display()),
        ('Reporting time', reporting.strftime('%H:%M')),
    ]
    if exam.instructions:
        details.append(('Instructions', exam.instructions))
    return details


def queue_duty_assignment(person, allocation):
    recipient, email, name, kind, person_id = _person_details(person)
    exam = allocation.exam_schedule
    key = (f'duty:{exam.pk}:{allocation.classroom_id}:{kind}:{person_id}:'
           f'{exam.date}:{exam.start_time}:{exam.end_time}:{allocation.role_type}')
    return queue_email(
        recipient_email=email, recipient_name=name, recipient=recipient,
        subject=f'Exam duty assignment · {exam.date:%d %b %Y} · {allocation.classroom.name}',
        notification_type=EmailNotification.Type.DUTY_ASSIGNMENT,
        template_key='duty_assignment', details=duty_email_details(allocation),
        idempotency_key=key,
        intro='An examination duty has been assigned to you. Please review the details below.',
    )


def queue_person_email(person, *, notification_type, template_key, subject,
                       details, idempotency_key, intro):
    recipient, email, name, _, _ = _person_details(person)
    return queue_email(recipient_email=email, recipient_name=name, recipient=recipient,
        notification_type=notification_type, template_key=template_key,
        subject=subject, details=details, idempotency_key=idempotency_key, intro=intro)


def _person_details(person):
    if person is None:
        return None, '', '', 'unknown', 'unknown'
    if hasattr(person, 'designation'):
        kind = 'faculty'
    else:
        kind = 'phd'
    user = getattr(person, 'user', None)
    return user, person.email, person.name, kind, person.pk


def queue_admin_email(*, subject, notification_type, template_key, details,
                      idempotency_prefix, intro):
    from django.contrib.auth import get_user_model
    users = get_user_model().objects.filter(is_staff=True).exclude(email='')
    for user in users:
        queue_email(recipient_email=user.email, recipient_name=user.get_full_name() or user.username,
            recipient=user, subject=subject, notification_type=notification_type,
            template_key=template_key, details=details,
            idempotency_key=f'{idempotency_prefix}:admin:{user.pk}', intro=intro)
