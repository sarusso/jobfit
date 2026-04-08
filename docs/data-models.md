# Data Models

## Overview

All models use UUID primary keys. `User` is a custom model extending Django's `AbstractUser`.
The file-based data store (`data/<username>/`) is retained for binary files (PDFs, CV files);
models store paths to those files rather than the files themselves.

## Models

| Model | Fields |
|---|---|
| **User** | `id` UUID PK · `username` · `email` · `password` · `first_name` · `last_name` · `is_staff` · `is_active` · `date_joined` *(extends AbstractUser)* |
| **LoginToken** | `id` UUID PK · `user` OneToOne FK→User · `token` |
| **Profile** | `id` UUID PK · `user` OneToOne FK→User · `timezone` · `type` · `plan` · `email_updates` · `last_accepted_terms` · `last_accepted_privacy` |
| **Company** | `id` UUID PK · `user` FK→User · `slug` · `name` · `description` · `archived` |
| **Job** | `id` UUID PK · `company` FK→Company · `title` · `location` · `employment_type` · `experience_level` · `summary` · `description` · `responsibilities` JSON · `requirements` JSON · `nice_to_have` JSON · `salary` · `source` ¹ · `source_file_path` ² · `added_at` · `archived` |
| **CV** | `id` UUID PK · `user` FK→User · `hash` · `name` · `file_path` |
| **Notes** | `id` UUID PK · `user` OneToOne FK→User · `content` · `updated_at` |
| **Score** | `id` UUID PK · `job` FK→Job · `cv` FK→CV · `mode` · `with_notes` TextField (nullable) ³ · `score` · `reasoning` · `strengths` JSON · `gaps` JSON |

¹ `source` — URL string, or `"file"` / `"text"`  
² `source_file_path` — nullable, path relative to the company folder, e.g. `<uuid>.pdf`  
³ `with_notes` — snapshot of notes content at scoring time; null if scored without notes  

## Score uniqueness

`unique_together = (job, cv, mode)` — one score per job/cv/mode combination, overwritten on re-score.

## File storage

Files remain on disk under `DATA_DIR/<username>/`:

```
<username>/
  _cv_<hash>.pdf              # referenced by CV.file_path
  <company_slug>/
    <job_uuid>.pdf            # referenced by Job.source_file_path
    <job_uuid>.txt            # referenced by Job.source_file_path (text import)
```
