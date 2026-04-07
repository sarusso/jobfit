import uuid
import logging

from django.db import models
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


class LoginToken(models.Model):
    user  = models.OneToOneField(User, on_delete=models.CASCADE)
    token = models.CharField('Login token', max_length=36)

    def __str__(self):
        return 'LoginToken for user "{}"'.format(self.user.email)


class Profile(models.Model):
    user                = models.OneToOneField(User, on_delete=models.CASCADE)
    email_updates       = models.BooleanField(default=False)
    last_accepted_terms = models.FloatField('Last accepted TOS', default=0)

    def __str__(self):
        return 'Profile of user "{}"'.format(self.user.email)
