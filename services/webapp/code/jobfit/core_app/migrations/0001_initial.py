from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0011_update_proxy_permissions'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginToken',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(max_length=36, verbose_name='Login token')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='auth.User')),
            ],
        ),
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email_updates', models.BooleanField(default=False)),
                ('last_accepted_terms', models.FloatField(default=0, verbose_name='Last accepted TOS')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='auth.User')),
            ],
        ),
    ]
