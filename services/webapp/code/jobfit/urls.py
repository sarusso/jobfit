import os
import django
import logging
from django.conf import settings
from django.conf.urls import url
from django.contrib import admin
from django.urls import path

from jobfit.core_app import views
from jobfit.core_app import jobs_views

logger = logging.getLogger(__name__)

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth
    url(r'^$',           views.home),
    url(r'^login/$',     views.user_login),
    url(r'^logout/$',    views.user_logout),
    url(r'^register/$',  views.register),
    url(r'^postlogin/$', views.postlogin),
    url(r'^account/$',   views.account),
    url(r'^privacy/$',   views.privacy),
    url(r'^terms/$',     views.terms),

    # Jobs app — settings
    url(r'^jobs/notes/save/$',  jobs_views.notes_save,      name='jobs_notes_save'),
    url(r'^jobs/set-mode/$',    jobs_views.set_mode,        name='jobs_set_mode'),
    url(r'^jobs/set-notes/$',   jobs_views.set_notes_mode,  name='jobs_set_notes'),

    # Jobs app — CV management (before generic company routes)
    url(r'^jobs/cv/upload/$',                       jobs_views.cv_upload,       name='jobs_cv_upload'),
    url(r'^jobs/cv/select/(?P<cv_hash>[^/]+)/$',   jobs_views.cv_select,       name='jobs_cv_select'),
    url(r'^jobs/cv/rename/(?P<cv_hash>[^/]+)/$',   jobs_views.cv_rename,       name='jobs_cv_rename'),
    url(r'^jobs/cv/delete/(?P<cv_hash>[^/]+)/$',   jobs_views.cv_delete,       name='jobs_cv_delete'),
    url(r'^jobs/cv/(?P<cv_hash>[^/]+)/$',          jobs_views.cv_view_specific, name='jobs_cv_view_specific'),
    url(r'^jobs/cv/$',                              jobs_views.cv_view,         name='jobs_cv_view'),

    # Jobs app — add jobs (before generic company routes)
    url(r'^jobs/add-jobs/url/$',                    jobs_views.add_job_url,         name='jobs_add_url'),
    url(r'^jobs/add-jobs/text/$',                   jobs_views.add_job_text,        name='jobs_add_text'),
    url(r'^jobs/add-jobs/scrape/categories/$',      jobs_views.scrape_categories,   name='jobs_scrape_categories'),
    url(r'^jobs/add-jobs/scrape/confirm/$',         jobs_views.scrape_confirm,      name='jobs_scrape_confirm'),
    url(r'^jobs/add-jobs/scrape/stream/$',          jobs_views.scrape_stream,       name='jobs_scrape_stream'),

    # Jobs app — scoring (before generic company routes)
    url(r'^jobs/score/(?P<company>[^/]+)/stream/$', jobs_views.score_company_stream, name='jobs_score_stream'),
    url(r'^jobs/score/(?P<company>[^/]+)/clear/$',  jobs_views.clear_scores,         name='jobs_score_clear'),
    url(r'^jobs/score/(?P<company>[^/]+)/(?P<role_id>[^/]+)/$', jobs_views.score_one, name='jobs_score_one'),

    # Jobs app — archive / delete (before generic company routes)
    url(r'^jobs/delete/(?P<company>[^/]+)/(?P<role_id>[^/]+)/$',   jobs_views.delete_job,       name='jobs_delete'),
    url(r'^jobs/archive/(?P<company>[^/]+)/(?P<role_id>[^/]+)/$',  jobs_views.archive_job,      name='jobs_archive_job'),
    url(r'^jobs/unarchive/(?P<company>[^/]+)/(?P<role_id>[^/]+)/$',jobs_views.unarchive_job,    name='jobs_unarchive_job'),
    url(r'^jobs/archive/(?P<company>[^/]+)/$',                     jobs_views.archive_company,  name='jobs_archive_company'),
    url(r'^jobs/unarchive/(?P<company>[^/]+)/$',                   jobs_views.unarchive_company, name='jobs_unarchive_company'),

    # Jobs app — browsing
    url(r'^jobs/help/$',                                              jobs_views.help_page,   name='jobs_help'),
    url(r'^jobs/$',                                                   jobs_views.index,       name='jobs_index'),
    url(r'^jobs/(?P<company>[^/]+)/(?P<role_id>[^/]+)/pdf/$',        jobs_views.job_pdf,     name='jobs_job_pdf'),
    url(r'^jobs/(?P<company>[^/]+)/(?P<role_id>[^/]+)/$',            jobs_views.job_view,    name='jobs_job'),
    url(r'^jobs/(?P<company>[^/]+)/$',                               jobs_views.company_view, name='jobs_company'),
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
