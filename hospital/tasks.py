"""Background jobs (Celery worker). The beat schedule in settings refreshes stale evidence and re-checks the pages
cited by WHO references every week."""
from celery import shared_task


@shared_task(ignore_result=True, soft_time_limit=180)
def refresh_evidence_task(key, code='', name='', unit=''):
    from .evidence import refresh_evidence
    refresh_evidence(key, code, name, unit)


@shared_task(ignore_result=True, soft_time_limit=1800)
def refresh_stale_evidence_task():
    """Re-fetch every cached result type whose sources are older than MEDICAL_EVIDENCE_MAX_AGE_DAYS."""
    from .evidence import fetch_enabled, refresh_evidence
    from .models import EvidenceFetch
    if not fetch_enabled():
        return
    for f in EvidenceFetch.objects.all():
        if f.stale and not f.busy:
            refresh_evidence(f.key, f.code, f.name, f.unit)


@shared_task(ignore_result=True, soft_time_limit=900)
def check_reference_sources_task():
    from .evidence import check_reference_sources, fetch_enabled
    if fetch_enabled():
        check_reference_sources()


@shared_task(ignore_result=True, soft_time_limit=300)
def ai_suggestion_task(pk):
    from .medical_ai import run_suggestion
    run_suggestion(pk)


@shared_task(ignore_result=True, soft_time_limit=300)
def report_assist_task(pk):
    from .reports import run_assist
    run_assist(pk)
