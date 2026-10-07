from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('allocation', '0002_classroom_seating')]

    operations = [
        migrations.AddField(
            model_name='phdscholar',
            name='email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AddField(
            model_name='phdscholar',
            name='subjects',
            field=models.ManyToManyField(blank=True, related_name='phd_scholars', to='allocation.subject'),
        ),
    ]
