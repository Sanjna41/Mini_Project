from django.contrib.auth.decorators import user_passes_test


def staff_required(view_func):
    """Allow only authenticated staff (admin) users."""
    return user_passes_test(lambda u: u.is_authenticated and u.is_staff)(view_func)

