"""The clinical library pages (see hospital/library.py)."""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render

from . import library as L
from .access import require
from .views import audit


@login_required
def index(request):
    require(request, 'library', 'Your access does not include the clinical library.')
    q, cat = request.GET.get('q', '').strip()[:60], request.GET.get('cat', '')[:30]
    return render(request, 'hospital/library/index.html', {**L.index(q, cat), 'q': q, 'cat': cat, 'total_curated': len(L.DISEASES)})


@login_required
def detail(request, slug):
    require(request, 'library', 'Your access does not include the clinical library.')
    d = L.detail(slug[:80])
    if not d:
        raise Http404
    from .categories import INFO
    audit(request, 'library_view', f'library:{slug[:60]}')
    return render(request, 'hospital/library/detail.html', {'d': d, 'catinfo': INFO.get(d['cat'])})
