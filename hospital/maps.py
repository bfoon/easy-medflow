"""Real maps (OpenStreetMap tiles) built with Folium. Leaflet itself is served from this server; only the map
tiles come from the internet."""
from urllib.parse import urlencode

import folium
from folium.plugins import HeatMap
from django.templatetags.static import static

GAMBIA_BOUNDS = [[13.05, -16.85], [13.83, -13.79]]

ESRI = 'Tiles &copy; Esri'


def tile_layers():
    """Base maps in order; the first is shown by default. All requested with only the site's origin as Referer."""
    from django.conf import settings
    layers = []
    if settings.MAP_TILE_URL:
        layers.append({'name': settings.MAP_TILE_NAME, 'url': settings.MAP_TILE_URL, 'attr': settings.MAP_TILE_ATTRIBUTION or 'Map tiles'})
    if settings.MAPTILER_KEY:
        layers.append({'name': 'Street map (MapTiler)', 'url': f'https://api.maptiler.com/maps/streets-v2/256/{{z}}/{{x}}/{{y}}.png?key={settings.MAPTILER_KEY}',
                       'attr': '&copy; MapTiler &copy; OpenStreetMap contributors'})
    layers += [
        {'name': 'Street map', 'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}',
         'attr': f'{ESRI} &mdash; Source: Esri, HERE, Garmin, USGS, OpenStreetMap contributors'},
        {'name': 'Satellite', 'url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
         'attr': f'{ESRI} &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community'},
        {'name': 'OpenStreetMap', 'url': 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', 'attr': '&copy; OpenStreetMap contributors'},
    ]
    return layers


def _local_assets(obj, js=(), css=()):
    obj.default_js = list(js)
    obj.default_css = list(css)


def health_map(points, explore_url, filters, active=''):
    """points: [{'name','label','lat','lon','n','all','region'}]. Bubble size = patients in this group; colour = share."""
    m = folium.Map(location=[13.45, -15.4], zoom_start=8, tiles=None, control_scale=True, prefer_canvas=True)
    _local_assets(m, js=[('leaflet', static('hospital/vendor/leaflet/leaflet.js')), ('jquery', static('hospital/vendor/leaflet/jquery.min.js'))],   # Folium popups need jQuery
                  css=[('leaflet_css', static('hospital/vendor/leaflet/leaflet.css'))])
    # Tile servers require the requesting site's origin (never the page address) in the Referer header.
    for i, t in enumerate(tile_layers()):
        folium.TileLayer(tiles=t['url'], attr=t['attr'], name=t['name'], show=i == 0, max_zoom=19,
                         referrerPolicy='strict-origin-when-cross-origin').add_to(m)
    bubbles = folium.FeatureGroup(name='Patients by location', show=True)
    mx = max([p['n'] for p in points] + [1])
    for p in points:
        share = p['n'] / p['all'] if p['all'] else 0
        colour = '#C8323F' if share >= .5 else '#E0912A' if share >= .25 else '#0F7B78'
        q = dict(filters, town=p['town'])
        link = f"{explore_url}?{urlencode({k: v for k, v in q.items() if v not in ('', None)})}"
        popup = (f"<div style='font:13px system-ui;min-width:170px'><b style='font-size:14px'>{p['label']}</b><br>"
                 f"<span style='color:#5A6F7D'>{p['region']}</span><hr style='margin:6px 0'>"
                 f"<b>{p['n']}</b> patient{'s' if p['n'] != 1 else ''} in this group<br>{p['all']} patients from here in total<br>"
                 f"<a href='{link}' target='_top' style='display:inline-block;margin-top:6px;color:#0F7B78;font-weight:700'>Explore {p['town']} →</a></div>")
        folium.CircleMarker(location=[p['lat'], p['lon']], radius=6 + (p['n'] / mx) ** .5 * 26, color='#0F2C3F' if p['town'] == active else colour,
                            weight=3 if p['town'] == active else 1.5, fill=True, fill_color=colour, fill_opacity=.35 + share * .45,
                            tooltip=f"{p['label']}: {p['n']} patients", popup=folium.Popup(popup, max_width=260)).add_to(bubbles)
    bubbles.add_to(m)
    if points:
        heat = HeatMap([[p['lat'], p['lon'], p['n']] for p in points], name='Heat map', radius=28, blur=22, min_opacity=.35, show=False)
        _local_assets(heat, js=[('leaflet-heat.js', static('hospital/vendor/leaflet/leaflet-heat.js'))])
        heat.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds(GAMBIA_BOUNDS if len(points) != 1 else [[points[0]['lat'] - .05, points[0]['lon'] - .07], [points[0]['lat'] + .05, points[0]['lon'] + .07]])
    return m.get_root().render()
