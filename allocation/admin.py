from django.contrib import admin

from .models import Classroom, DutyAllocation, ExamSchedule, Faculty, PhDScholar, UFMRecord, Section, Seating, SeatingAllotment, Student, Subject, ExamSession, Availability, TimetableEntry, ReplacementRequest, Notification, SessionSeating, SessionSeatingAllotment, StudentSubjectRegistration, ImportBatch, EmailNotification


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'designation', 'duty_quota')
    list_filter = ('designation',)
    search_fields = ('name', 'email')


@admin.register(PhDScholar)
class PhDScholarAdmin(admin.ModelAdmin):
    list_display = ('name', 'duty_quota')
    search_fields = ('name',)


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('name', 'rows', 'columns', 'capacity')
    search_fields = ('name',)


@admin.register(ExamSchedule)
class ExamScheduleAdmin(admin.ModelAdmin):
    list_display = ('date', 'slot', 'start_time', 'end_time')
    list_filter = ('date', 'slot')


@admin.register(DutyAllocation)
class DutyAllocationAdmin(admin.ModelAdmin):
    list_display = (
        'exam_schedule',
        'classroom',
        'role_type',
        'faculty',
        'phd_scholar',
        'detained_round',
    )
    list_filter = ('exam_schedule', 'classroom', 'role_type', 'detained_round')
    search_fields = ('faculty__name', 'phd_scholar__name')


@admin.register(UFMRecord)
class UFMRecordAdmin(admin.ModelAdmin):
    list_display = ('faculty', 'phd_scholar', 'exam_schedule', 'count', 'created_at')
    list_filter = ('exam_schedule',)
    search_fields = ('faculty__name', 'phd_scholar__name')


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'coordinator')
    search_fields = ('name', 'coordinator__name', 'coordinator__email')
admin.site.register(Section)
admin.site.register(Student)
admin.site.register(Seating)
admin.site.register(SeatingAllotment)
admin.site.register(ExamSession)
admin.site.register(Availability)
admin.site.register(TimetableEntry)
admin.site.register(ReplacementRequest)
admin.site.register(Notification)
admin.site.register(SessionSeating)
admin.site.register(SessionSeatingAllotment)
admin.site.register(StudentSubjectRegistration)
admin.site.register(ImportBatch)


@admin.register(EmailNotification)
class EmailNotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient_email', 'subject', 'notification_type', 'status', 'attempt_count', 'created_at', 'sent_at')
    list_filter = ('status', 'notification_type', 'created_at')
    search_fields = ('recipient_email', 'recipient_name', 'subject')
    readonly_fields = ('recipient', 'recipient_email', 'recipient_name', 'subject', 'notification_type', 'status', 'idempotency_key', 'text_body', 'html_body', 'attempt_count', 'last_error', 'created_at', 'last_attempt_at', 'sent_at')

