import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core_app', '0010_user_is_demo'),
    ]

    operations = [
        migrations.CreateModel(
            name='KnownFit',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('marked_at', models.DateTimeField(auto_now_add=True)),
                ('cv', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='known_fits', to='core_app.CV')),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='known_fits', to='core_app.Job')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='known_fits', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user', 'job', 'cv')},
            },
        ),
    ]
