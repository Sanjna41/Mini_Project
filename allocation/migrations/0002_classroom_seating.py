from django.db import migrations, models
import django.db.models.deletion


def copy_capacity_to_columns(apps, schema_editor):
    Classroom = apps.get_model('allocation', 'Classroom')
    for room in Classroom.objects.all():
        room.rows = 1
        room.columns = room.capacity
        room.save(update_fields=['rows', 'columns'])


class Migration(migrations.Migration):
    dependencies = [('allocation', '0001_initial')]
    operations = [
        migrations.CreateModel(name='Section', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('name', models.CharField(max_length=50, unique=True))]),
        migrations.CreateModel(name='Subject', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('name', models.CharField(max_length=100, unique=True))]),
        migrations.AddField(model_name='classroom', name='columns', field=models.PositiveIntegerField(null=True)),
        migrations.AddField(model_name='classroom', name='rows', field=models.PositiveIntegerField(null=True)),
        migrations.RunPython(copy_capacity_to_columns, migrations.RunPython.noop),
        migrations.AlterField(model_name='classroom', name='columns', field=models.PositiveIntegerField()),
        migrations.AlterField(model_name='classroom', name='rows', field=models.PositiveIntegerField()),
        migrations.RemoveField(model_name='classroom', name='capacity'),
        migrations.CreateModel(name='Student', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('name', models.CharField(blank=True, max_length=100)), ('roll_no', models.PositiveIntegerField()), ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='students', to='allocation.section'))], options={'ordering': ['roll_no'], 'unique_together': {('section', 'roll_no')}}),
        migrations.AddField(model_name='faculty', name='subjects', field=models.ManyToManyField(blank=True, related_name='faculty_members', to='allocation.subject')),
        migrations.AddField(model_name='examschedule', name='subject', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='allocation.subject')),
        migrations.CreateModel(name='ExamSection', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('position', models.PositiveIntegerField()), ('exam_schedule', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='exam_sections', to='allocation.examschedule')), ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='allocation.section'))], options={'ordering': ['position']}),
        migrations.AddField(model_name='examschedule', name='sections', field=models.ManyToManyField(blank=True, through='allocation.ExamSection', to='allocation.section')),
        migrations.AddConstraint(model_name='examsection', constraint=models.UniqueConstraint(fields=('exam_schedule', 'section'), name='unique_exam_section')),
        migrations.AddConstraint(model_name='examsection', constraint=models.UniqueConstraint(fields=('exam_schedule', 'position'), name='unique_exam_section_position')),
        migrations.CreateModel(name='Seating', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('seat_no', models.PositiveIntegerField()), ('row_no', models.PositiveIntegerField()), ('col_no', models.PositiveIntegerField()), ('roll_no', models.PositiveIntegerField()), ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seatings', to='allocation.classroom')), ('exam_schedule', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seatings', to='allocation.examschedule')), ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seatings', to='allocation.section'))]),
        migrations.AddConstraint(model_name='seating', constraint=models.UniqueConstraint(fields=('exam_schedule', 'roll_no'), name='unique_exam_roll_seating')),
        migrations.AddConstraint(model_name='seating', constraint=models.UniqueConstraint(fields=('exam_schedule', 'classroom', 'row_no', 'col_no'), name='unique_exam_room_position')),
        migrations.CreateModel(name='SeatingAllotment', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('from_roll_no', models.PositiveIntegerField()), ('to_roll_no', models.PositiveIntegerField()), ('classroom', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seating_allotments', to='allocation.classroom')), ('exam_schedule', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seating_allotments', to='allocation.examschedule')), ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seating_allotments', to='allocation.section'))], options={'ordering': ['classroom__name', 'from_roll_no']}),
    ]
