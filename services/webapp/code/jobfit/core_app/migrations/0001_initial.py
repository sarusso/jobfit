import uuid
import django.contrib.auth.models
import django.contrib.auth.validators
import django.contrib.postgres.fields
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0011_update_proxy_permissions'),
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
                ('first_name', models.CharField(blank=True, max_length=30, verbose_name='first name')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
                ('email', models.EmailField(max_length=254, unique=True, verbose_name='email address')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.Group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.Permission', verbose_name='user permissions')),
            ],
            options={
                'verbose_name': 'user',
                'verbose_name_plural': 'users',
                'abstract': False,
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Company',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('slug', models.CharField(max_length=255)),
                ('name', models.CharField(blank=True, max_length=255)),
                ('description', models.TextField(blank=True)),
                ('archived', models.BooleanField(default=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='companies', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='CV',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('hash', models.CharField(max_length=64)),
                ('name', models.CharField(max_length=255)),
                ('file_path', models.CharField(max_length=500)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cvs', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Job',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(blank=True, max_length=500)),
                ('location', models.CharField(blank=True, max_length=255)),
                ('employment_type', models.CharField(blank=True, max_length=100)),
                ('experience_level', models.CharField(blank=True, max_length=100)),
                ('summary', models.TextField(blank=True)),
                ('description', models.TextField(blank=True)),
                ('responsibilities', django.contrib.postgres.fields.JSONField(blank=True, default=list)),
                ('requirements', django.contrib.postgres.fields.JSONField(blank=True, default=list)),
                ('nice_to_have', django.contrib.postgres.fields.JSONField(blank=True, default=list)),
                ('salary', models.CharField(blank=True, max_length=255)),
                ('source', models.CharField(blank=True, max_length=2048)),
                ('source_file_path', models.CharField(blank=True, max_length=500)),
                ('added_at', models.DateTimeField(auto_now_add=True)),
                ('archived', models.BooleanField(default=False)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='jobs', to='core_app.Company')),
            ],
        ),
        migrations.CreateModel(
            name='LoginToken',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('token', models.CharField(max_length=36, verbose_name='Login token')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Notes',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('content', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='notes', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('timezone', models.CharField(default='UTC', max_length=36, verbose_name='User Timezone')),
                ('type', models.CharField(default='Standard', max_length=36, verbose_name='Profile type')),
                ('plan', models.CharField(default='Free', max_length=36, verbose_name='User plan')),
                ('email_updates', models.BooleanField(default=False)),
                ('last_accepted_terms', models.FloatField(default=0, verbose_name='Last accepted TOS')),
                ('last_accepted_privacy', models.FloatField(default=0, verbose_name='Last accepted Privacy Policy')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Score',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('mode', models.CharField(default='normal', max_length=20)),
                ('with_notes', models.TextField(blank=True, null=True)),
                ('score', models.IntegerField()),
                ('reasoning', models.TextField(blank=True)),
                ('strengths', django.contrib.postgres.fields.JSONField(blank=True, default=list)),
                ('gaps', django.contrib.postgres.fields.JSONField(blank=True, default=list)),
                ('cv', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scores', to='core_app.CV')),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scores', to='core_app.Job')),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='score',
            unique_together={('job', 'cv', 'mode')},
        ),
        migrations.AlterUniqueTogether(
            name='cv',
            unique_together={('user', 'hash')},
        ),
        migrations.AlterUniqueTogether(
            name='company',
            unique_together={('user', 'slug')},
        ),
    ]
