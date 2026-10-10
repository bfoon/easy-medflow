from django.db.models import Q


def medflow(request):
    """Navigation badges and the signed-in staff role, available to every template."""
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return {}
    from .models import QueueTicket, LabOrder, LabRequest, Prescription, Referral, WorkflowRun
    from .views import role_of
    return {
        'nav_role': role_of(request.user) or 'unassigned',
        'nav_counts': {
            'queue': QueueTicket.objects.filter(status='waiting').count(),
            'labs': LabRequest.objects.filter(orders__status__in=['ordered', 'collected', 'processing', 'resulted']).distinct().count(),
            'pharmacy': Prescription.objects.filter(state__in=['draft', 'signed']).count(),
            'referrals': Referral.objects.filter(Q(status='sent') | Q(status='accepted')).count(),
            'studio': WorkflowRun.objects.filter(status='open').count(),
        },
    }
