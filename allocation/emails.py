"""Compatibility helpers for code that used the former email sender."""
import logging

from .email_notifications import queue_duty_assignment

logger = logging.getLogger(__name__)


def send_duty_allocation_email(user_or_profile, allocations):
    """Queue assignments using the persisted email outbox.

    Older internal code passed the linked Django User; newer callers pass the
    Faculty/PhDScholar profile directly. Both forms now share deduplication,
    templates, delivery tracking, and post-commit delivery.
    """
    profile = user_or_profile
    if not hasattr(profile, 'email'):
        profile = getattr(user_or_profile, 'faculty_profile', None) or getattr(user_or_profile, 'phd_profile', None)
    if profile is None:
        logger.warning('Skipped legacy duty email call because the account has no faculty or PhD profile.')
        return []
    return [queue_duty_assignment(profile, allocation) for allocation in allocations]
