"""Explicit local configuration and Google credential discovery."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_config(path=None):
    """Environment wins. The ignored local .env is the only auto-loaded file."""
    path = Path(path) if path else ROOT / '.env'
    if not path.is_file():
        return
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError(f'Invalid configuration line {number}')
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if not key.replace('_', '').isalnum():
            raise ValueError(f'Invalid configuration key on line {number}')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            os.environ.setdefault(key, value)


def google_credentials():
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError
    scopes = ['https://www.googleapis.com/auth/cloud-platform']
    try:
        credential, _ = google.auth.default(scopes=scopes)
        return credential
    except DefaultCredentialsError:
        from .firestore_client import FirebaseConfig
        config = FirebaseConfig.from_environment()
        if config.credentials == 'adc':
            raise
        from google.oauth2.service_account import Credentials
        return Credentials.from_service_account_file(config.credentials, scopes=scopes)
