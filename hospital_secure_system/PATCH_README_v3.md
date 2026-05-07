# Hospital Secure System PATCH v3 - Ambulance UI

This patch updates only the dashboard UI.

## What changed
- Ambulance red/white professional theme.
- Login screen disappears after successful login.
- Header shows logged-in user/admin name and role.
- Logout button in the header.
- Smoother cards, layout, transitions, and admin/user experience.
- Browser still uses JWT only; internal API keys remain server-side through env variables.

## How to apply
Copy the `dashboard/index.html` file over your current project file.

Then run:

```bash
docker compose up -d --build nginx
```

Open:

```text
https://localhost
```

If the old dashboard is cached, hard refresh with Ctrl + F5.
