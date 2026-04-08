import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core_app', '0003_llmpricing_profile_usage'),
    ]

    operations = [
        migrations.CreateModel(
            name='GiftCode',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('code', models.CharField(max_length=64, unique=True)),
                ('amount', models.DecimalField(decimal_places=4, max_digits=10)),
                ('expires_at', models.DateTimeField()),
                ('redeemed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='redeemed_codes', to=settings.AUTH_USER_MODEL)),
                ('redeemed_at', models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='CreditLedger',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ledger_entries', to=settings.AUTH_USER_MODEL)),
                ('amount', models.DecimalField(decimal_places=4, max_digits=10)),
                ('description', models.CharField(max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
