import os
import django
import django.views.static
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
    url(r'^demo/$',      views.demo_login),
    url(r'^register/$',  views.register),
    url(r'^postlogin/$', views.postlogin),
    url(r'^account/$',                    views.account),
    url(r'^account/redeem/$',             views.redeem_gift_code),
    url(r'^account/admin/create-code/$',  views.create_gift_code),
    url(r'^backend/$',                    views.backend_home,       name='backend'),
    url(r'^backend/gift-codes/$',         views.backend_gift_codes, name='backend_gift_codes'),
    url(r'^backend/users/$',              views.backend_users,      name='backend_users'),
    url(r'^backend/analytics/$',          views.backend_analytics,  name='backend_analytics'),
    url(r'^about/$',     views.about),
    url(r'^privacy/$',  views.privacy),
    url(r'^terms/$',    views.terms),

    # Jobs app — settings
    path('jobs/notes/save/',  jobs_views.notes_save,     name='jobs_notes_save'),
    path('jobs/set-mode/',    jobs_views.set_mode,       name='jobs_set_mode'),
    path('jobs/set-notes/',   jobs_views.set_notes_mode, name='jobs_set_notes'),

    # Jobs app — CV management (before generic company routes)
    path('jobs/cv/upload/',                    jobs_views.cv_upload,        name='jobs_cv_upload'),
    path('jobs/cv/select/<uuid:cv_id>/',       jobs_views.cv_select,        name='jobs_cv_select'),
    path('jobs/cv/rename/<uuid:cv_id>/',       jobs_views.cv_rename,        name='jobs_cv_rename'),
    path('jobs/cv/delete/<uuid:cv_id>/',       jobs_views.cv_delete,        name='jobs_cv_delete'),
    path('jobs/cv/<uuid:cv_id>/',              jobs_views.cv_view_specific, name='jobs_cv_view_specific'),
    path('jobs/cv/',                           jobs_views.cv_view,          name='jobs_cv_view'),

    # Jobs app — add jobs (before generic company routes)
    path('jobs/add-jobs/url/',                   jobs_views.add_job_url,       name='jobs_add_url'),
    path('jobs/add-jobs/text/',                  jobs_views.add_job_text,      name='jobs_add_text'),
    path('jobs/add-jobs/scrape/categories/',     jobs_views.scrape_categories, name='jobs_scrape_categories'),
    path('jobs/add-jobs/scrape/confirm/',        jobs_views.scrape_confirm,    name='jobs_scrape_confirm'),
    path('jobs/add-jobs/scrape/stream/',         jobs_views.scrape_stream,     name='jobs_scrape_stream'),
    path('jobs/add-jobs/scrape/pdf-extract/',    jobs_views.extract_pdf_jobs,  name='jobs_scrape_pdf_extract'),

    # Jobs app — scoring (before generic company routes)
    path('jobs/score/<slug:company_slug>/stream/', jobs_views.score_company_stream, name='jobs_score_stream'),
    path('jobs/score/<slug:company_slug>/clear/',  jobs_views.clear_scores,         name='jobs_score_clear'),
    path('jobs/score/<slug:company_slug>/<uuid:job_id>/', jobs_views.score_one,     name='jobs_score_one'),
    path('jobs/known-fit/<slug:company_slug>/<uuid:job_id>/', jobs_views.toggle_known_fit, name='jobs_toggle_known_fit'),

    # Jobs app — archive / delete (before generic company routes)
    path('jobs/delete/<slug:company_slug>/<uuid:job_id>/',    jobs_views.delete_job,        name='jobs_delete'),
    path('jobs/archive/<slug:company_slug>/<uuid:job_id>/',   jobs_views.archive_job,       name='jobs_archive_job'),
    path('jobs/unarchive/<slug:company_slug>/<uuid:job_id>/', jobs_views.unarchive_job,     name='jobs_unarchive_job'),
    path('jobs/archive/<slug:company_slug>/',                 jobs_views.archive_company,   name='jobs_archive_company'),
    path('jobs/unarchive/<slug:company_slug>/',               jobs_views.unarchive_company, name='jobs_unarchive_company'),

    # Jobs app — browsing
    path('help/',                                               jobs_views.help_page,    name='jobs_help'),
    path('jobs/',                                               jobs_views.index,        name='jobs_index'),
    path('jobs/<slug:company_slug>/<uuid:job_id>/pdf/',         jobs_views.job_pdf,      name='jobs_job_pdf'),
    path('jobs/<slug:company_slug>/<uuid:job_id>/',             jobs_views.job_view,     name='jobs_job'),
    path('jobs/<slug:company_slug>/',                           jobs_views.company_view, name='jobs_company'),
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
