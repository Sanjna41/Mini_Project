from django.db import migrations, models
import django.db.models.deletion


def backfill_coordinators(apps, schema_editor):
    Subject = apps.get_model('allocation', 'Subject')
    Faculty = apps.get_model('allocation', 'Faculty')
    ExamSchedule = apps.get_model('allocation', 'ExamSchedule')
    DutyAllocation = apps.get_model('allocation', 'DutyAllocation')
    through = Faculty.subjects.through
    alias = schema_editor.connection.alias
    for subject in Subject.objects.using(alias).all():
        ids = list(through.objects.using(alias).filter(subject_id=subject.pk)
                   .values_list('faculty_id', flat=True).distinct())
        if len(ids) == 1:
            Subject.objects.using(alias).filter(pk=subject.pk).update(coordinator_id=ids[0])
    for exam in ExamSchedule.objects.using(alias).select_related('subject').all():
        if not exam.subject_id:
            ExamSchedule.objects.using(alias).filter(pk=exam.pk).update(coordinator_status='NONE')
            continue
        DutyAllocation.objects.using(alias).filter(exam_schedule_id=exam.pk).update(subject_id=exam.subject_id)
        coordinator_id = Subject.objects.using(alias).filter(pk=exam.subject_id).values_list('coordinator_id', flat=True).first()
        if coordinator_id:
            match = DutyAllocation.objects.using(alias).filter(exam_schedule_id=exam.pk, faculty_id=coordinator_id).order_by('pk').first()
            if match:
                DutyAllocation.objects.using(alias).filter(pk=match.pk).update(is_subject_coordinator=True)
                ExamSchedule.objects.using(alias).filter(pk=exam.pk).update(coordinator_status='ASSIGNED')
            else:
                ExamSchedule.objects.using(alias).filter(pk=exam.pk).update(coordinator_status='PENDING', coordinator_note='Coordinator must be assigned by rerunning allocation.')
        else:
            ExamSchedule.objects.using(alias).filter(pk=exam.pk).update(coordinator_status='UNRESOLVED', coordinator_note='No unique faculty coordinator could be inferred from the legacy subject links.')


class Migration(migrations.Migration):
    dependencies = [('allocation', '0012_examschedule_examination_type')]
    operations = [
        migrations.AddField(model_name='subject', name='coordinator', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='coordinated_subjects', to='allocation.faculty')),
        migrations.AddField(model_name='examschedule', name='coordinator_status', field=models.CharField(choices=[('NONE', 'No subject coordinator required'), ('PENDING', 'Coordinator duty pending'), ('ASSIGNED', 'Coordinator duty assigned'), ('UNRESOLVED', 'Coordinator duty unresolved')], db_index=True, default='NONE', max_length=12)),
        migrations.AddField(model_name='examschedule', name='coordinator_note', field=models.TextField(blank=True)),
        migrations.AddField(model_name='dutyallocation', name='subject', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='duty_allocations', to='allocation.subject')),
        migrations.AddField(model_name='dutyallocation', name='is_subject_coordinator', field=models.BooleanField(default=False)),
        migrations.RunPython(backfill_coordinators, migrations.RunPython.noop),
        migrations.AddConstraint(model_name='dutyallocation', constraint=models.UniqueConstraint(condition=models.Q(('is_subject_coordinator', True)), fields=('exam_schedule',), name='one_subject_coordinator_per_exam')),
        migrations.AddConstraint(model_name='dutyallocation', constraint=models.CheckConstraint(condition=models.Q(('is_subject_coordinator', False), ('faculty__isnull', False), ('phd_scholar__isnull', True), _connector='OR'), name='coordinator_duty_must_be_faculty')),
    ]
