import os
import logging
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'your-secret-key-here'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = False

ALLOWED_HOSTS = [
    'localhost',
    '192.168.1.27',
    '127.0.0.1',
    'freetool.us',
    'www.freetool.us',
    'api.freetool.us',
    '104.207.71.55',
    'server1.freetool.us',
]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework',
    'corsheaders',
    'rest_framework_simplejwt',
    'django_downloadview',
    
    # Your apps
    'myapp.apps.MyappConfig',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    )
}

from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=5),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': False,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',
    'JTI_CLAIM': 'jti',
    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
}

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'myapp.middleware.TransactionLoggingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# CORS settings
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    # للتطوير المحلي
    "http://localhost:3000",
    "http://localhost:4173",
    "http://localhost:5173",
    "http://localhost:8080",
    
    "http://127.0.0.1:3000",
    "http://127.0.0.1:4173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8080",
    
    # IP addresses
    "http://192.168.1.20:8080",
    "http://192.168.1.20:4173",
    
    # للإنتاج - HTTPS
    "https://freetool.us",
    "https://www.freetool.us",
    "https://api.freetool.us",
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost:\d+$",
    r"^http://127\.0\.0\.1:\d+$",
]

CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-api-key',
    'x-requested-with',
    'x-file-name',
    'x-file-size',
]

CORS_EXPOSE_HEADERS = [
    'content-disposition',
    'x-original-size',
    'x-converted-size',
    'x-saved-bytes',
    'x-compression-ratio'
]

CORS_PREFLIGHT_MAX_AGE = 86400

ROOT_URLCONF = 'myproject.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'myproject.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Custom Settings for No-Auth JWT ---
STATIC_API_KEY = os.environ.get('STATIC_API_KEY', 'your-super-secret-api-key')
MACHINE_USERNAME = os.environ.get('MACHINE_USERNAME', 'machine_user')
ALLOW_MACHINE_TOKEN_WITHOUT_API_KEY = os.environ.get('ALLOW_MACHINE_TOKEN_WITHOUT_API_KEY', str(DEBUG)).lower() in ('1', 'true', 'yes')
# --- End Custom Settings ---

# إعدادات الأمان لـ HTTPS
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Logging
class IgnoreBrokenPipeFilter(logging.Filter):
    def filter(self, record):
        return "Broken pipe from" not in record.getMessage()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'filters': {
        'ignore_broken_pipe': {
            '()': 'myproject.settings.IgnoreBrokenPipeFilter',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
            'filters': ['ignore_broken_pipe'],
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs/image_to_pdf.log',
            'formatter': 'verbose',
            'filters': ['ignore_broken_pipe'],
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
        },
        'myapp': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}

# Create logs directory if it doesn't exist
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

# File upload settings
DATA_UPLOAD_MAX_MEMORY_SIZE = 104857600  # 100MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 104857600  # 100MB

# File storage settings
FILE_STORAGE_PATH = os.path.join(BASE_DIR, 'files')

# Ensure the files directory exists
os.makedirs(FILE_STORAGE_PATH, exist_ok=True)
os.makedirs(os.path.join(FILE_STORAGE_PATH, 'uploads'), exist_ok=True)
os.makedirs(os.path.join(FILE_STORAGE_PATH, 'converted'), exist_ok=True)
os.makedirs(os.path.join(FILE_STORAGE_PATH, 'temp'), exist_ok=True)
