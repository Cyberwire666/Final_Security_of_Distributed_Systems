from pathlib import Path
import secrets

ENV_PATH = Path('.env')
TEMPLATE_PATH = Path('.env.example')


def upsert(lines, key, value):
    prefix = key + '='
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = prefix + value
            return lines
    lines.append(prefix + value)
    return lines

if not ENV_PATH.exists():
    if TEMPLATE_PATH.exists():
        ENV_PATH.write_text(TEMPLATE_PATH.read_text(encoding='utf-8'), encoding='utf-8')
    else:
        ENV_PATH.write_text('', encoding='utf-8')

lines = ENV_PATH.read_text(encoding='utf-8').splitlines()
secrets_to_write = {
    'JWT_SECRET': secrets.token_urlsafe(64),
    'INTERNAL_API_KEY': secrets.token_urlsafe(48),
    'POSTGRES_PASSWORD': secrets.token_urlsafe(24),
    'RABBITMQ_DEFAULT_PASS': secrets.token_urlsafe(24),
    'OAUTH_STATE': secrets.token_urlsafe(32),
}

try:
    from cryptography.fernet import Fernet
    secrets_to_write['FERNET_KEY'] = Fernet.generate_key().decode()
except Exception:
    print('cryptography is not installed locally. Install it or run scripts/generate_keys.py for FERNET_KEY.')

for key, value in secrets_to_write.items():
    lines = upsert(lines, key, value)

ENV_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print('Updated .env successfully with generated secrets:')
for key in secrets_to_write:
    print(f'- {key}')
