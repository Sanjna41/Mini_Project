from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings


def send_duty_allocation_email(user, allocations):
    """
    Send duty allocation email to a faculty or PhD scholar.
    allocations = list of DutyAllocation objects for this user
    """
    if not user.email:
        return  

    subject = "📋 Your Exam Duty Allocation — ExamDutyManager"
    duty_lines = []
    duty_lines.extend([
        {
            "course":    alloc.exam.course_name,
            "date":      alloc.exam.date,
            "slot":      alloc.exam.get_time_slot_display(),
            "time":      f"{alloc.exam.start_time} - {alloc.exam.end_time}",
            "classroom": alloc.classroom.name,
            "role":      alloc.get_role_display(),
        }
        for alloc in allocations
    ])

    message = _build_plain_text(user, duty_lines)
    html_message = _build_html(user, duty_lines)

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        print(f"✅ Email sent to {user.email}")
    except Exception as e:
        print(f"❌ Failed to send email to {user.email}: {e}")


def _build_plain_text(user, duty_lines):
    """Plain text version of the email."""
    name = user.get_full_name() or user.username
    lines = [
        f"Dear {name},",
        "",
        "Your exam duty has been allocated. Please find the details below:",
        "",
    ]
    for i, duty in enumerate(duty_lines, start=1):
        lines.extend([
            f"Duty {i}:",
            f"  Course   : {duty['course']}",
            f"  Date     : {duty['date']}",
            f"  Slot     : {duty['slot']}",
            f"  Time     : {duty['time']}",
            f"  Classroom: {duty['classroom']}",
            f"  Role     : {duty['role']}",
            "",
        ])

    lines += [
        "Please be present on time.",
        "",
        "Regards,",
        "ExamDutyManager",
    ]
    return "\n".join(lines)


def _build_html(user, duty_lines):
    """HTML version of the email."""
    name = user.get_full_name() or user.username

    rows = "".join(f"""
        <tr>
            <td style="padding:8px; border:1px solid #dee2e6;">{duty['course']}</td>
            <td style="padding:8px; border:1px solid #dee2e6;">{duty['date']}</td>
            <td style="padding:8px; border:1px solid #dee2e6;">{duty['slot']}</td>
            <td style="padding:8px; border:1px solid #dee2e6;">{duty['time']}</td>
            <td style="padding:8px; border:1px solid #dee2e6;">{duty['classroom']}</td>
            <td style="padding:8px; border:1px solid #dee2e6;">{duty['role']}</td>
        </tr>
        """ for duty in duty_lines)

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; background:#f8f9fa; padding:20px;">

        <div style="max-width:600px; margin:auto; background:white;
                    border-radius:12px; overflow:hidden;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.1);">

            <!-- Header -->
            <div style="background: linear-gradient(135deg, #0d6efd, #0a58ca);
                        padding:24px; text-align:center;">
                <h1 style="color:white; margin:0; font-size:20px;">
                    📋 ExamDutyManager
                </h1>
                <p style="color:rgba(255,255,255,0.8); margin:4px 0 0;">
                    Duty Allocation Notification
                </p>
            </div>

            <!-- Body -->
            <div style="padding:24px;">
                <p style="font-size:16px;">Dear <strong>{name}</strong>,</p>
                <p style="color:#6c757d;">
                    Your exam duty has been allocated.
                    Please find the details below and be present on time.
                </p>

                <!-- Duty Table -->
                <table style="width:100%; border-collapse:collapse;
                              font-size:14px; margin-top:16px;">
                    <thead>
                        <tr style="background:#0d6efd; color:white;">
                            <th style="padding:10px; text-align:left;">Course</th>
                            <th style="padding:10px; text-align:left;">Date</th>
                            <th style="padding:10px; text-align:left;">Slot</th>
                            <th style="padding:10px; text-align:left;">Time</th>
                            <th style="padding:10px; text-align:left;">Classroom</th>
                            <th style="padding:10px; text-align:left;">Role</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>

                <!-- Alert box -->
                <div style="background:#fff3cd; border:1px solid #ffc107;
                            border-radius:8px; padding:12px; margin-top:20px;">
                    <strong>⚠️ Important:</strong>
                    Please be present at the classroom 10 minutes before the exam starts.
                </div>

                <p style="margin-top:24px; color:#6c757d; font-size:13px;">
                    If you have any questions, please contact the exam coordinator.
                </p>
            </div>

            <!-- Footer -->
            <div style="background:#f8f9fa; padding:16px; text-align:center;
                        border-top:1px solid #dee2e6;">
                <small style="color:#6c757d;">
                    This is an automated email from ExamDutyManager.
                    Please do not reply to this email.
                </small>
            </div>

        </div>
    </body>
    </html>
    """