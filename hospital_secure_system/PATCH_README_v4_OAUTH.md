# PATCH v4 - GitHub OAuth

This patch adds GitHub OAuth login to the Hospital Secure System.

## Files changed
- `services/auth-service/main.py`
- `dashboard/index.html`
- `.env.example`
- `scripts/generate_secrets.py`

## Setup

1. Replace these files over your current project.
2. Open `.env` and add:

```env
GITHUB_CLIENT_ID=your_github_oauth_client_id
GITHUB_CLIENT_SECRET=your_github_oauth_client_secret
OAUTH_REDIRECT_URI=https://localhost/api/auth/oauth/github/callback
OAUTH_STATE=any_long_random_string
OAUTH_DEFAULT_ROLE=user
```

3. If you want to auto-generate `OAUTH_STATE`, run:

```bash
python scripts/generate_secrets.py
```

4. In your GitHub OAuth App settings, set the callback URL exactly to:

```text
https://localhost/api/auth/oauth/github/callback
```

5. Rebuild only the needed containers:

```bash
docker compose up -d --build auth-service nginx
```

6. Open:

```text
https://localhost
```

Then click **Continue with GitHub OAuth**.

## Notes
- OAuth users are created automatically if they do not exist.
- Existing users with the same email are linked to GitHub.
- A normal system JWT is issued after OAuth login.
- The login screen disappears after OAuth success because the token is stored in browser localStorage.
