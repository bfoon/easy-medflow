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


@shared_task(ignore_result=True, soft_time_limit=300)
def imaging_ai_task(pk):
    from .imaging_ai import run
    run(pk)


@shared_task(ignore_result=True, soft_time_limit=300)
def drflow_ask_task(pk):
    from .drflow_ask import run_ask
    run_ask(pk)


@shared_task(ignore_result=True, soft_time_limit=300)
def bed_summary_task(pk):
    from .bed_summary import run
    run(pk)


@shared_task(ignore_result=True, soft_time_limit=300)
def notes_ai_task(pk):
    from .notes_ai import run
    run(pk)


@shared_task(ignore_result=True, soft_time_limit=300)
def lab_insight_task(pk):
    from .lab_insights_ai import run
    run(pk)


@shared_task(ignore_result=True, soft_time_limit=900)
def programme_sweep_task():
    """Care programmes: reminders, missed visits, escalations and lost to follow-up (programmes.sweep)."""
    from .programmes import sweep
    return sweep()


@shared_task(ignore_result=True, soft_time_limit=300)
def programme_ai_task(pk):
    from .programmes import run_ai
    run_ai(pk)
