from django.contrib import admin
from .models import Profile, LoginToken

admin.site.register(Profile)
admin.site.register(LoginToken)
