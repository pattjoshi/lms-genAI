# Sign-in, roles and the public site

Until now the login page let you "pick a user" and the frontend sent that user's id in a header the
backend trusted. This change replaces it with real authentication and keeps the old picker as a
**dev-only demo login**.

## How logging in works

1. **Email and password** (`POST /auth/login`) or **Google** (`POST /auth/google`).
2. The backend checks the password (scrypt hash, `app/accounts/passwords.py`) or Google's signed ID token
   (`app/accounts/google.py`: signature, our client id, issuer, expiry, verified email).
3. It creates a row in `auth_sessions` and sets an **httpOnly cookie** `lms_session` holding a random id.
   The database stores only the id's SHA-256, so a leaked backup can't log anyone in.
4. Every API call sends the cookie (`credentials: "include"` in `lib/api.ts`). `get_current_user`
   (`app/auth.py`) looks the session up; expired, revoked or deactivated means **401**.
5. **Logout**, a **password change** (other browsers) and **deactivation** by an admin end sessions at once.
   That is why sessions live in the database and not in a JWT.

Extra protections: 5 wrong passwords lock that email for 15 minutes (`AUTH_MAX_FAILED_LOGINS`,
`AUTH_LOCKOUT_MINUTES`); "wrong email" and "wrong password" get the same message; writes from another
site are refused (Origin check in `app/main.py`); every attempt is written to `login_events`, so support
and the SQL agent see real login problems. Credentials live in `user_credentials`, which the SQL agent
has no grant on.

## Roles (authorization)

The roles are unchanged: **student, teacher (instructor), support, admin**.

| Layer | Where | What it does |
| --- | --- | --- |
| Route guard | `require_roles(...)` in `app/auth.py` | a student calling an admin endpoint gets 403 |
| Data scope | `app/permissions.py`, `app/scopes.py` | what rows each role may see |
| Database | row-level security (Phase 6) | the SQL agent can't read past the matrix |
| UI | `PortalShell` | not logged in → `/login?next=…`; wrong role → your own portal |

The UI guard is only for convenience; the backend enforces everything.

- **Sign-up only creates students.** Nobody can make themselves an admin.
- **Admins give roles** on **Users & roles** (`/admin/users`): add a user with a first password, change a
  role, deactivate. An admin can't demote or deactivate themselves, so there is always an admin.

## Your own accounts

**The first admin** (sign-up can't create one):

```powershell
cd backend
uv run python -m app.accounts create-admin --email you@example.com --name "Your Name"
```

It asks for a password (not shown, not saved in shell history). If you already signed up on the
website with that email, the account is promoted to admin. Then log in at <http://localhost:3000/login>.

Other commands:

```powershell
uv run python -m app.accounts set-password --email someone@example.com   # reset a forgotten password
uv run python -m app.accounts set-role --email someone@example.com --role teacher
```

**Students** sign up at `/signup` (or with Google). **Teachers and support** sign up, then an admin
changes their role, or the admin adds them directly on Users & roles.

**Seeded demo users** have no passwords. With `APP_ENV=dev` and `AUTH_DEMO_LOGIN=true` (the defaults) the
login page has a **Demo accounts** section to log in as any of them. It is off whenever `APP_ENV` isn't
`dev`. To give a seeded user a real password, use `set-password`.

## Google sign-in (optional)

1. <https://console.cloud.google.com> → APIs & Services → Credentials → **Create credentials → OAuth client ID**
   → **Web application** (set up the consent screen first if asked).
2. **Authorized JavaScript origins**: `http://localhost:3000` (and your production URL later).
   No redirect URI is needed.
3. Put the client id in `.env`: `GOOGLE_CLIENT_ID=1234-abc.apps.googleusercontent.com`, restart the backend.

The "Continue with Google" button appears on log-in and sign-up. A Google account whose verified email
matches an existing user is linked to it; otherwise a new student account is created (if sign-up is open).

## Production checklist

- `APP_ENV=production` (turns off demo login and technical error details).
- Serve over https and set `AUTH_COOKIE_SECURE=true`.
- Frontend and backend on the same site (`app.example.com` + `api.example.com`): keep `AUTH_COOKIE_SAMESITE=lax`.
  Different sites: `none` (needs https).
- `FRONTEND_ORIGIN` = the exact frontend URL (CORS and the Origin check use it).
- `AUTH_SIGNUP_OPEN=false` if only admins should create accounts.
- Password reset by email isn't built yet; admins use `set-password`.

## Public pages

| Page | What |
| --- | --- |
| `/` | landing: hero with search, live stats, categories, popular courses, how it works, features, audiences, testimonials, pricing, FAQ |
| `/courses` | catalogue with search, category, level and sort (kept in the URL) |
| `/login`, `/signup` | email + password, Google, demo accounts in dev |

They read `GET /public/catalog` and `GET /public/stats` (no login; only catalogue data and totals). The
testimonials and the plan prices on the landing page are sample copy: replace them in `app/page.tsx` and
`components/site/Pricing.tsx` before launch.
