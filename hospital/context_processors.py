from django.db.models import Q


def medflow(request):
    """Navigation badges and the signed-in staff role, available to every template."""
    embed = request.GET.get('embed') == '1' or request.POST.get('embed') == '1'
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {'embed': embed}
    from .models import Invoice, ImagingOrder, QueueTicket, LabOrder, LabRequest, Prescription, Referral, WorkflowRun
    from .views import role_of
    from . import flows
    from .models import Envelope
    return {
        'embed': embed,
        'nav_role': role_of(request.user) or 'unassigned',
        'caps': __import__('hospital.access', fromlist=['caps']).caps(request.user),
        'nav_counts': {
            'queue': QueueTicket.objects.filter(status='waiting').count(),
            'labs': LabRequest.objects.filter(orders__status__in=['ordered', 'collected', 'processing', 'resulted']).distinct().count(),
            'pharmacy': Prescription.objects.filter(state__in=['draft', 'signed']).count(),
            'referrals': Referral.objects.filter(direction='in', status='sent').count(),   # new referrals waiting in our inbox
            'studio': flows.tasks_for(request.user).count(),                                 # steps waiting for this person
            'esign': Envelope.objects.filter(status='sent', recipients__user=request.user, recipients__status__in=['sent', 'viewed']).distinct().count(),
            'imaging': ImagingOrder.objects.filter(status__in=['requested', 'acquired']).count(),
            'bills': Invoice.objects.filter(status='draft').count(),
            'theatre': __import__('hospital.theatre', fromlist=['active_count']).active_count(),
            'mortality': _mortality_count(request.user),
            'ambulance': __import__('hospital.models_ambulance', fromlist=['EmergencyCall']).EmergencyCall.objects.filter(status__in=['new', 'waiting']).count(),
            'programmes': __import__('hospital.models_programmes', fromlist=['ProgrammeVisit']).ProgrammeVisit.objects.filter(
                status='missed', enrolment__status__in=['active', 'lost']).filter(Q(enrolment__clinician=request.user) | Q(enrolment__nurse=request.user)).count(),
        },
    }


def _mortality_count(user):
    """Deaths without a certificate (for those who certify) plus open autopsies (for pathology)."""
    from .access import has
    from .models_mortality import Autopsy, DeathRecord
    n = 0
    if has(user, 'death_certify'):
        n += DeathRecord.objects.exclude(status='revoked').filter(certified_at__isnull=True).count()
    if has(user, 'autopsy'):
        n += Autopsy.objects.filter(status__in=['consented', 'scheduled', 'in_progress', 'preliminary']).count()
    return n
