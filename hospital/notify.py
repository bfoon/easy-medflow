"""Notifications: the in-app bell, plus email for staff who have an address and have not turned email off.

Emails carry only a title and a link back into E-MedFlow, never patient details: the reader must sign in to see more.
"""
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone


def _email(ids):
    from .models import Notification
    for n in Notification.objects.filter(pk__in=ids).select_related('user', 'user__hospital_staff'):
        prof = getattr(n.user, 'hospital_staff', None)
        if not n.user.email or (prof and not prof.email_notifications):
            continue
        link = settings.SITE_URL.rstrip('/') + (n.url or '/')
        try:
            send_mail(f'E-MedFlow · {n.title}', f'{n.title}\n\n{n.body}\n\nOpen in E-MedFlow: {link}\n\n'
                      'For privacy, patient details are only shown after you sign in.', settings.DEFAULT_FROM_EMAIL, [n.user.email], fail_silently=True)
            Notification.objects.filter(pk=n.pk).update(emailed_at=timezone.now())
        except Exception:      # never let email problems break the clinical workflow
            pass


def notify(users, title, body='', url='', kind='info', exclude=None):
    """Create a notification for each user (deduplicated), and email them after the current transaction commits."""
    from .models import Notification
    seen, ids = set(), []
    for u in users:
        if not u or u.pk in seen or (exclude and u.pk == exclude.pk) or not u.is_active:
            continue
        seen.add(u.pk)
        ids.append(Notification.objects.create(user=u, kind=kind, title=title[:200], body=body[:400], url=url[:300]).pk)
    if ids:
        sync = getattr(settings, 'NOTIFY_EMAIL_SYNC', False)
        transaction.on_commit(lambda: _email(ids) if sync else threading.Thread(target=_email, args=(ids,), daemon=True).start())
    return len(ids)


# ------------------------------------------------------------------ who should hear about a referral
def _active(qs):
    return [p.user for p in qs.select_related('user') if p.active and p.user.is_active]


def referral_receivers(r):
    """People on the receiving side: the specialist's own login(s) and/or the facility's staff, or (inbound) our doctors."""
    from .models import StaffProfile
    if r.direction == 'in':
        return _active(StaffProfile.objects.filter(role__in=['doctor', 'admin']))
    people = []
    if r.specialist_id:
        people += _active(StaffProfile.objects.filter(role='specialist', specialist_id=r.specialist_id))
    if r.facility_id:
        people += _active(StaffProfile.objects.filter(role='partner', facility_id=r.facility_id))
    return people


def referral_senders(r):
    from .models import StaffProfile
    people = [r.created_by] if r.created_by else []
    if r.direction == 'in' and r.from_facility_id:
        people += _active(StaffProfile.objects.filter(role='partner', facility_id=r.from_facility_id))
    elif r.encounter.clinician:
        people.append(r.encounter.clinician)
    return people
