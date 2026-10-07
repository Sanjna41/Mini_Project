from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('allocation', '0003_phdscholar_email_subjects')]

    operations = [
        migrations.RemoveConstraint(
            model_name='seating',
            name='unique_exam_roll_seating',
        ),
        migrations.AddConstraint(
            model_name='seating',
            constraint=models.UniqueConstraint(
                fields=('exam_schedule', 'section', 'roll_no'),
                name='unique_exam_section_roll_seating',
            ),
        ),
    ]
