import os
import django
import logging
from django.conf import settings
from django.conf.urls import url
from django.contrib import admin
from django.urls import path

from jobfit.core_app import views

logger = logging.getLogger(__name__)

urlpatterns = [
    path('admin/', admin.site.urls),

    url(r'^$',           views.home),
    url(r'^login/$',     views.user_login),
    url(r'^logout/$',    views.user_logout),
    url(r'^register/$',  views.register),
    url(r'^postlogin/$', views.postlogin),
    url(r'^account/$',   views.account),
    url(r'^privacy/$',   views.privacy),
    url(r'^terms/$',     views.terms),
]

# Serve static files in non-debug mode
admin_files_path = '/'.join(django.__file__.split('/')[0:-1]) + '/contrib/admin/static/admin'

if not settings.DEBUG:
    urlpatterns.append(url(r'^static/admin/(?P<path>.*)$', django.views.static.serve, {'document_root': admin_files_path}))
    document_root = 'jobfit/core_app/static'
    if os.path.isdir(document_root):
        logger.info('Serving static files from "%s"', document_root)
        urlpatterns.append(url(r'^static/(?P<path>.*)$', django.views.static.serve, {'document_root': document_root}))
else:
    logger.info('Not serving static files at all as DEBUG=True (Django will do it automatically)')
