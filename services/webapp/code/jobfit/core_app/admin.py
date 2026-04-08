from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group

from .models import User, LoginToken, Profile, Company, Job, CV, Notes, Score

# Remove Group (unused) and the default auth section clutter
admin.site.unregister(Group)


class UserAdmin(BaseUserAdmin):
    pass


admin.site.register(User, UserAdmin)


@admin.register(LoginToken)
class LoginTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'token')


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'timezone', 'type', 'plan', 'email_updates')


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'user', 'archived')
    list_filter  = ('archived',)
    search_fields = ('name', 'slug', 'user__username')


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display  = ('title', 'company', 'employment_type', 'experience_level', 'added_at', 'archived')
    list_filter   = ('archived', 'employment_type', 'experience_level')
    search_fields = ('title', 'company__name', 'company__slug')
    raw_id_fields = ('company',)


@admin.register(CV)
class CVAdmin(admin.ModelAdmin):
    list_display  = ('name', 'user', 'hash', 'uploaded_at')
    search_fields = ('name', 'user__username')


@admin.register(Notes)
class NotesAdmin(admin.ModelAdmin):
    list_display  = ('user', 'updated_at')
    search_fields = ('user__username',)


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display  = ('job', 'cv', 'mode', 'score')
    list_filter   = ('mode',)
    raw_id_fields = ('job', 'cv')
