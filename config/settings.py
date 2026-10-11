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
X_FRAME_OPTIONS = 'SAMEORIGIN'  # pages may be framed only by MedFlow itself (the slide-out panel); other sites are still blocked

CELERY_BROKER_URL = env('REDIS_URL', default='redis://redis:6379/0')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

# Clinical AI (off by default). When enabled, only de-identified context is sent, from the server, to this endpoint.
CLINICAL_AI_ENABLED = env.bool('CLINICAL_AI_ENABLED', False)
CLINICAL_AI_ENDPOINT = env('CLINICAL_AI_ENDPOINT', default='')
CLINICAL_AI_TOKEN = env('CLINICAL_AI_TOKEN', default='')

# Map tiles. The first layer is the default; users can switch in the map's layer box.
# Free without a key: Esri street map and satellite, OpenStreetMap. Set MAPTILER_KEY (free key from maptiler.com)
# to make MapTiler the main map, or MAP_TILE_URL/MAP_TILE_ATTRIBUTION for your own provider.
MAPTILER_KEY = env('MAPTILER_KEY', default='')
MAP_TILE_URL = env('MAP_TILE_URL', default='')
MAP_TILE_ATTRIBUTION = env('MAP_TILE_ATTRIBUTION', default='')
MAP_TILE_NAME = env('MAP_TILE_NAME', default='Custom map')
