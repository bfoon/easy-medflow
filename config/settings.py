from pathlib import Path
import sys
import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DJANGO_DEBUG=(bool, False), SECURE_SSL_REDIRECT=(bool, False), USE_SQLITE=(bool, False))
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('DJANGO_SECRET_KEY', default='dev-only-insecure-change-me')
DEBUG = env.bool('DJANGO_DEBUG', False)
TESTING = 'test' in sys.argv
if not DEBUG and not TESTING and SECRET_KEY == 'dev-only-insecure-change-me':
    raise RuntimeError('Set DJANGO_SECRET_KEY')

ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])
CSRF_TRUSTED_ORIGINS = env.list('DJANGO_CSRF_TRUSTED_ORIGINS', default=[])

INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'django.contrib.humanize',
    'hospital',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'hospital.access.PatientScopeMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'hospital.context_processors.medflow',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'

# USE_SQLITE=True gives a zero-dependency local dev database; Docker/production uses PostgreSQL.
if env.bool('USE_SQLITE', False):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': env('SQLITE_PATH', default=str(BASE_DIR / 'db.sqlite3'))}}
else:
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': env('POSTGRES_DB', default='medflow'), 'USER': env('POSTGRES_USER', default='medflow'),
        'PASSWORD': env('POSTGRES_PASSWORD', default=''), 'HOST': env('POSTGRES_HOST', default='db'),
        'PORT': env('POSTGRES_PORT', default='5432'), 'CONN_MAX_AGE': 60,
    }}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = env('TIME_ZONE', default='Africa/Banjul')
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage' if (DEBUG or TESTING)
                    else 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', False)
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)  # set e.g. 31536000 once HTTPS is permanent
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'SAMEORIGIN'  # pages may be framed only by E-MedFlow itself (the slide-out panel); other sites are still blocked

CELERY_BROKER_URL = env('REDIS_URL', default='redis://redis:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_BROKER_CONNECTION_TIMEOUT = 3          # never hold up a page for long if Redis is down
CELERY_TASK_ALWAYS_EAGER = TESTING            # tests run background jobs in-process
from celery.schedules import crontab  # noqa: E402
CELERY_BEAT_SCHEDULE = {   # runs when the worker is started with -B (see compose files)
    'refresh-stale-medical-evidence': {'task': 'hospital.tasks.refresh_stale_evidence_task', 'schedule': crontab(hour=2, minute=30, day_of_week='sun')},
    'check-who-reference-sources': {'task': 'hospital.tasks.check_reference_sources_task', 'schedule': crontab(hour=3, minute=0, day_of_week='sun')},
    'care-programme-sweep': {'task': 'hospital.tasks.programme_sweep_task', 'schedule': crontab(minute=10)},   # hourly; reminders go out from 07:00
}

# Clinical AI (off by default). When enabled, only de-identified context is sent, from the server.
# Provider 'anthropic' (Claude API, ANTHROPIC_API_KEY) or 'endpoint' (your own approved service). Blank = anthropic if a key is set.
CLINICAL_AI_ENABLED = env.bool('CLINICAL_AI_ENABLED', False)
CLINICAL_AI_PROVIDER = env('CLINICAL_AI_PROVIDER', default='')
CLINICAL_AI_ENDPOINT = env('CLINICAL_AI_ENDPOINT', default='')
CLINICAL_AI_TOKEN = env('CLINICAL_AI_TOKEN', default='')
ANTHROPIC_API_KEY = env('ANTHROPIC_API_KEY', default='')
ANTHROPIC_BASE_URL = env('ANTHROPIC_BASE_URL', default='https://api.anthropic.com')
CLINICAL_AI_MODEL = env('CLINICAL_AI_MODEL', default='claude-sonnet-5-5')
CLINICAL_AI_WEB_SEARCH = env.bool('CLINICAL_AI_WEB_SEARCH', True)     # let the AI search trusted medical sites
CLINICAL_AI_MAX_SEARCHES = env.int('CLINICAL_AI_MAX_SEARCHES', default=5)
CLINICAL_AI_MAX_TOKENS = env.int('CLINICAL_AI_MAX_TOKENS', default=3000)
CLINICAL_AI_TIMEOUT = env.int('CLINICAL_AI_TIMEOUT', default=120)

CLINICAL_AI_RETRIES = env.int('CLINICAL_AI_RETRIES', default=3)
CLINICAL_AI_FALLBACK_MODEL = env('CLINICAL_AI_FALLBACK_MODEL', default='')

# Lab result guidance: summaries from trusted medical sources (WHO, MedlinePlus, PubMed), fetched in the background.
# Only test names and the direction of a result are sent to these sites, never patient data. Off in tests.
MEDICAL_EVIDENCE_FETCH = env.bool('MEDICAL_EVIDENCE_FETCH', default=not TESTING)
# Dr. Flow pictures from NLM Open-i and Wikimedia Commons (no patient data is sent). Unset = follow MEDICAL_EVIDENCE_FETCH.
DRFLOW_IMAGES = env.bool('DRFLOW_IMAGES', default=None) if not TESTING else False
MEDICAL_EVIDENCE_MAX_AGE_DAYS = env.int('MEDICAL_EVIDENCE_MAX_AGE_DAYS', default=30)
MEDICAL_TRUSTED_DOMAINS = env.list('MEDICAL_TRUSTED_DOMAINS', default=[
    'who.int', 'nih.gov', 'medlineplus.gov', 'cdc.gov', 'nice.org.uk', 'msf.org', 'cochranelibrary.com', 'bmj.com', 'thelancet.com', 'nejm.org'])
NCBI_EMAIL = env('NCBI_EMAIL', default='')        # NCBI asks E-utilities users for a contact email
NCBI_API_KEY = env('NCBI_API_KEY', default='')    # optional: raises the PubMed rate limit from 3 to 10 requests/second

# Map tiles. The first layer is the default; users can switch in the map's layer box.
# Free without a key: Esri street map and satellite, OpenStreetMap. Set MAPTILER_KEY (free key from maptiler.com)
# to make MapTiler the main map, or MAP_TILE_URL/MAP_TILE_ATTRIBUTION for your own provider.
MAPTILER_KEY = env('MAPTILER_KEY', default='')
MAP_TILE_URL = env('MAP_TILE_URL', default='')
MAP_TILE_ATTRIBUTION = env('MAP_TILE_ATTRIBUTION', default='')
MAP_TILE_NAME = env('MAP_TILE_NAME', default='Custom map')

# Email (notifications). Development prints emails to the web log; set these in .env to send real email.
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='E-MedFlow <no-reply@e-medflow.local>')
SITE_URL = env('SITE_URL', default='http://localhost:8000')   # used for links in emails
# Care programmes: the clinic name in patient reminders, and an optional SMS gateway (JSON POST {"to", "message"} with a
# Bearer token). Without a gateway, SMS and WhatsApp reminders wait in the programme outbox for staff to send in one tap.
MEDFLOW_CLINIC_NAME = env('MEDFLOW_CLINIC_NAME', default='')
PROGRAMME_SMS_URL = env('PROGRAMME_SMS_URL', default='')
PROGRAMME_SMS_TOKEN = env('PROGRAMME_SMS_TOKEN', default='')
