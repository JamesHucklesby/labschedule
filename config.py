import os
import re

from dotenv import load_dotenv

load_dotenv()

# ── Google OAuth ──────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:8080/auth/callback')
GOOGLE_HOSTED_DOMAIN = os.getenv('GOOGLE_HOSTED_DOMAIN', 'aucklanduni.ac.nz')
GOOGLE_LOGIN_HINT = os.getenv('GOOGLE_LOGIN_HINT', '').strip() or None
GOOGLE_OAUTH_SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
]

# ── App ───────────────────────────────────────────────────────────────────────
_DEFAULT_APP_SECRET_KEY = 'dev-secret-key-change-in-production'
APP_SECRET_KEY = os.getenv('APP_SECRET_KEY', _DEFAULT_APP_SECRET_KEY)
APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:8080').strip().rstrip('/')
APP_ENV = os.getenv('APP_ENV', 'development').strip().lower()
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'auto').strip().lower()
TRUSTED_PROXY_IPS = {
    ip.strip()
    for ip in os.getenv('TRUSTED_PROXY_IPS', '127.0.0.1,::1').split(',')
    if ip.strip()
}

if APP_ENV in {'production', 'prod'} and APP_SECRET_KEY == _DEFAULT_APP_SECRET_KEY:
    raise RuntimeError('APP_SECRET_KEY must be set to a strong secret in production.')

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv('DATABASE_URL', '').strip() or None
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost').strip()
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_DB = os.getenv('POSTGRES_DB', 'calendar').strip()
POSTGRES_USER = os.getenv('POSTGRES_USER', 'postgres').strip()
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', '')
POSTGRES_SSLMODE = os.getenv('POSTGRES_SSLMODE', 'prefer').strip()
POSTGRES_CONNECT_TIMEOUT_SECONDS = int(os.getenv('POSTGRES_CONNECT_TIMEOUT_SECONDS', '5'))

# ── Email login / SMTP ───────────────────────────────────────────────────────
SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com').strip()
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '').strip()
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '').strip()
SMTP_USE_STARTTLS = os.getenv('SMTP_USE_STARTTLS', 'true').strip().lower() in {'1', 'true', 'yes', 'on'}
SMTP_FROM_EMAIL = os.getenv('SMTP_FROM_EMAIL', SMTP_USERNAME).strip()
SMTP_FROM_NAME = os.getenv('SMTP_FROM_NAME', 'Lab Scheduler').strip()
EMAIL_LOGIN_TOKEN_TTL_MINUTES = int(os.getenv('EMAIL_LOGIN_TOKEN_TTL_MINUTES', '15'))

# ── JWT ───────────────────────────────────────────────────────────────────────
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_EXP_SECONDS = int(os.getenv('JWT_EXP_SECONDS', '43200'))

# ── Roles ─────────────────────────────────────────────────────────────────────
DEFAULT_USER_ROLE = 'user'
ADMIN_USER_ROLE = 'admin'
ADMIN_USER_EMAILS: set[str] = {'jhuc964@aucklanduni.ac.nz'}
ADMIN_USER_NAMES: set[str] = {'James Hucklesby'}

# ── Input validation ──────────────────────────────────────────────────────────
MAX_TEXT_INPUT_LENGTH = 256
MAX_TOKEN_INPUT_LENGTH = 1024
MAX_CALENDAR_IDS_PER_REQUEST = 200
MAX_NOTES_INPUT_LENGTH = 8000
_CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x1f\x7f]')
_UNSAFE_NOTES_CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
_TOKEN_PATTERN = re.compile(r'^[A-Za-z0-9]{16,1024}$')
_EMAIL_PATTERN = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

# ── OAuth state ───────────────────────────────────────────────────────────────
OAUTH_STATE_TTL_SECONDS = 600

# ── Rate limiting ─────────────────────────────────────────────────────────────
TOKEN_RATE_LIMIT_WINDOW_SECONDS = 1.0
TOKEN_RATE_LIMIT_MAX_REQUESTS = 10

# ── Test / seed calendars ─────────────────────────────────────────────────────
