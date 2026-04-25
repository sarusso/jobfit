import uuid
import logging
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from .fields import JSONField
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


class User(AbstractUser):
    id      = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email   = models.EmailField(unique=True)
    is_demo = models.BooleanField(default=False)


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
    plan                  = models.CharField('User plan', max_length=36, default='pay_as_you_go')
    email_updates         = models.BooleanField(default=False)
    last_accepted_terms   = models.FloatField('Last accepted TOS', default=0)
    last_accepted_privacy = models.FloatField('Last accepted Privacy Policy', default=0)
    usage                 = JSONField(default=dict, blank=True)
    scoring_mode          = models.CharField(max_length=20, default='normal')
    use_notes             = models.BooleanField(default=False)
    selected_cv           = models.ForeignKey('CV', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def get_balance(self) -> Decimal:
        result = TopUp.objects.filter(
            user=self.user,
            residual_credits__gt=0,
        ).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
        ).aggregate(b=Sum('residual_credits'))['b']
        return result if result is not None else Decimal('0.00')

    def __str__(self):
        return f'Profile of user "{self.user.email}"'


class LLMPricing(models.Model):
    provider      = models.CharField(max_length=50)   # e.g. "openai"
    model         = models.CharField(max_length=100)  # e.g. "gpt-4o"
    # price keys match OpenAI usage field names, values are USD per 1M tokens
    # e.g. {"completion_tokens": 10.0, "prompt_tokens": 2.5}
    price         = JSONField()
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-id']

    def pricing_key(self):
        return "-".join(str(self.price[k]) for k in sorted(self.price))

    def __str__(self):
        return f'{self.provider}/{self.model} [{self.pricing_key()}]{"" if self.superseded_at is None else " (superseded)"}'


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
    STATUS_NONE         = 'none'
    STATUS_TO_APPLY     = 'to_apply'
    STATUS_APPLIED      = 'applied'
    STATUS_IN_PROGRESS  = 'in_progress'
    STATUS_GOT_RESPONSE = 'got_response'
    STATUS_CHOICES = (
        (STATUS_NONE,         '—'),
        (STATUS_TO_APPLY,     'To apply'),
        (STATUS_APPLIED,      'Applied'),
        (STATUS_IN_PROGRESS,  'In progress'),
        (STATUS_GOT_RESPONSE, 'Got response'),
    )

    id                 = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company            = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='jobs')
    title              = models.CharField(max_length=500, blank=True)
    location           = models.CharField(max_length=255, blank=True)
    employment_type    = models.CharField(max_length=100, blank=True)
    experience_level   = models.CharField(max_length=100, blank=True)
    summary            = models.TextField(blank=True)
    description        = models.TextField(blank=True)
    responsibilities   = JSONField(default=list, blank=True)
    requirements       = JSONField(default=list, blank=True)
    nice_to_have       = JSONField(default=list, blank=True)
    salary             = models.CharField(max_length=255, blank=True)
    other              = models.TextField(blank=True)
    # source: URL string if imported from URL, "file" or "text" otherwise
    source             = models.CharField(max_length=2048, blank=True)
    # source_file_path: relative to user data dir, e.g. "jobs/<uuid>.pdf"
    source_file_path   = models.CharField(max_length=500, blank=True)
    added_at           = models.DateTimeField(auto_now_add=True)
    archived           = models.BooleanField(default=False)
    status             = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NONE)
    status_updated_at  = models.DateTimeField(null=True, blank=True)
    applied_at         = models.DateTimeField(null=True, blank=True)
    notes              = models.TextField(blank=True)

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


class GiftCode(models.Model):
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code          = models.CharField(max_length=64, unique=True)
    description   = models.CharField(max_length=255, blank=True)          # internal label
    credits       = models.DecimalField(max_digits=10, decimal_places=2)  # credits granted on redemption
    expires_at    = models.DateTimeField()                                # deadline to redeem
    validity_days = models.PositiveIntegerField(null=True, blank=True)    # days top-up valid after redemption
    redeemed_by   = models.ForeignKey('User', null=True, blank=True, on_delete=models.SET_NULL, related_name='redeemed_codes')
    redeemed_at   = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.code} ({self.credits} cr)'


class TopUp(models.Model):
    id               = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user             = models.ForeignKey('User', on_delete=models.CASCADE, related_name='topups')
    credits          = models.DecimalField(max_digits=10, decimal_places=2)  # purchased credits
    residual_credits = models.DecimalField(max_digits=10, decimal_places=2)  # remaining credits
    created_at       = models.DateTimeField(auto_now_add=True)
    expires_at       = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['expires_at', 'created_at']

    def __str__(self):
        return f'TopUp {self.credits} cr (residual {self.residual_credits} cr) for {self.user.email}'


class UsageLog(models.Model):
    TYPE_JOB_IMPORT = 0
    TYPE_CV_SCORING = 1
    TYPE_CHOICES = (
        (TYPE_JOB_IMPORT, 'Job import'),
        (TYPE_CV_SCORING, 'CV scoring'),
    )

    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user            = models.ForeignKey('User', on_delete=models.CASCADE, related_name='usage_logs')
    credits_charged = models.DecimalField(max_digits=10, decimal_places=2)  # credits deducted
    usd_cost        = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)  # real LLM cost, internal
    type            = models.IntegerField(choices=TYPE_CHOICES, null=True, blank=True, default=None)
    description     = models.CharField(max_length=100)                      # macro category, e.g. "CV scoring"
    detail          = models.CharField(max_length=255, blank=True)          # internal: provider/model/tokens
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'-{self.credits_charged} cr — {self.description} [{self.detail}] ({self.user.email})'


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


class KnownFit(models.Model):
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user      = models.ForeignKey('User', on_delete=models.CASCADE, related_name='known_fits')
    job       = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='known_fits')
    cv        = models.ForeignKey(CV, on_delete=models.CASCADE, related_name='known_fits')
    marked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'job', 'cv')

    def __str__(self):
        return f'KnownFit {self.job} / {self.cv}'
