from django.contrib import admin

from .models import Classroom, DutyAllocation, ExamSchedule, Faculty, PhDScholar, UFMRecord, Section, Seating, SeatingAllotment, Student, Subject


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


admin.site.register(Subject)
admin.site.register(Section)
admin.site.register(Student)
admin.site.register(Seating)
admin.site.register(SeatingAllotment)

