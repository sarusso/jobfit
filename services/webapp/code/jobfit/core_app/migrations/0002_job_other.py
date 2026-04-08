from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core_app', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='job',
            name='other',
            field=models.TextField(blank=True, default=''),
            preserve_default=False,
        ),
    ]
