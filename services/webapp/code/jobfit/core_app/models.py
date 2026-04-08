import uuid
import logging

from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.fields import JSONField
from django.db import models

logger = logging.getLogger(__name__)


class User(AbstractUser):
    id    = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)


class LoginToken(models.Model):
    id    = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user  = models.OneToOneField('User', on_delete=models.CASCADE)
    token = models.CharField('Login token', max_length=36)

    def __str__(self):
        return f'LoginToken for user "{self.user.email}"'


class Profile(models.Model):
    id                    = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user                  = models.OneToOneField('User', on_delete=models.CASCADE)
    timezone              = models.CharField('User Timezone', max_length=36, default='UTC')
    type                  = models.CharField('Profile type', max_length=36, default='Standard')
    plan                  = models.CharField('User plan', max_length=36, default='Free')
    email_updates         = models.BooleanField(default=False)
    last_accepted_terms   = models.FloatField('Last accepted TOS', default=0)
    last_accepted_privacy = models.FloatField('Last accepted Privacy Policy', default=0)

    def __str__(self):
        return f'Profile of user "{self.user.email}"'


class Company(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey('User', on_delete=models.CASCADE, related_name='companies')
    slug        = models.CharField(max_length=255)
    name        = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    archived    = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'slug')

    def __str__(self):
        return self.name or self.slug


class Job(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company          = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='jobs')
    title            = models.CharField(max_length=500, blank=True)
    location         = models.CharField(max_length=255, blank=True)
    employment_type  = models.CharField(max_length=100, blank=True)
    experience_level = models.CharField(max_length=100, blank=True)
    summary          = models.TextField(blank=True)
    description      = models.TextField(blank=True)
    responsibilities = JSONField(default=list, blank=True)
    requirements     = JSONField(default=list, blank=True)
    nice_to_have     = JSONField(default=list, blank=True)
    salary           = models.CharField(max_length=255, blank=True)
    # source: URL string if imported from URL, "file" or "text" otherwise
    source           = models.CharField(max_length=2048, blank=True)
    # source_file_path: relative to user data dir, e.g. "jobs/<uuid>.pdf"
    source_file_path = models.CharField(max_length=500, blank=True)
    added_at         = models.DateTimeField(auto_now_add=True)
    archived         = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.title} @ {self.company}'


class CV(models.Model):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey('User', on_delete=models.CASCADE, related_name='cvs')
    hash        = models.CharField(max_length=64)
    name        = models.CharField(max_length=255)
    # file_path: relative to user data dir, e.g. "_cvs/<hash>.pdf"
    file_path   = models.CharField(max_length=500)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'hash')

    def __str__(self):
        return f'{self.name} ({self.user.email})'


class Notes(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.OneToOneField('User', on_delete=models.CASCADE, related_name='notes')
    content    = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Notes for {self.user.email}'


class Score(models.Model):
    MODE_NORMAL = 'normal'
    MODE_BRUTAL = 'brutal'

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job        = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='scores')
    cv         = models.ForeignKey(CV, on_delete=models.CASCADE, related_name='scores')
    mode       = models.CharField(max_length=20, default=MODE_NORMAL)
    # with_notes: snapshot of notes content used at scoring time; null if scored without notes
    with_notes = models.TextField(blank=True, null=True)
    score      = models.IntegerField()
    reasoning  = models.TextField(blank=True)
    strengths  = JSONField(default=list, blank=True)
    gaps       = JSONField(default=list, blank=True)

    class Meta:
        unique_together = ('job', 'cv', 'mode')

    def __str__(self):
        return f'Score {self.score} for {self.job} with {self.cv}'
