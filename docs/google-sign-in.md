# Setting up Sign in with Google

mental signs people in with Google's standard OAuth flow. It needs a Google OAuth client, which you
make once in Google Cloud Console. Without one the app still runs, guest-only.

## 1. Make the client

1. Open https://console.cloud.google.com and create a project (e.g. "mental").
2. **APIs & Services → OAuth consent screen**: choose **External**, give an app name and your
   email. No extra scopes are needed: mental asks only for `openid`. While the app is in
   **Testing**, add your own Google account under **Test users**. Only test users can sign in
   until you publish the app.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**, type
   **Web application**. Under **Authorized redirect URIs** add exactly:
   - `http://127.0.0.1:8000/auth/callback` (running on your machine)
   - later, `https://<your domain>/auth/callback` (when it goes online)
4. Copy the **Client ID** and **Client secret**.

## 2. Give them to mental

mental reads them from environment variables, so nothing secret is in the repo:

    export MENTAL_GOOGLE_CLIENT_ID=<client id>
    export MENTAL_GOOGLE_CLIENT_SECRET=<client secret>
    uv run mental

Put the two `export` lines somewhere outside the repo (e.g. your shell profile) and never commit them.
Open the app at **http://127.0.0.1:8000** (not `localhost`). The sign-in cookie belongs to the
address you opened, and Google sends you back to the registered address. Open one and come back on
the other and the cookie is lost, so sign-in fails.

## 3. When it goes online

Set `MENTAL_BASE_URL=https://<your domain>` on the server as well as the two variables above, and
make sure that domain's redirect address is in the client's list. On `https`, mental's cookies
become `Secure` and host-only automatically.

## Before going online

mental is built for running on your own machine. Before putting it on the internet:

- check the `Origin` header on the POST and PUT routes;
- rate-limit `/auth/google` and cap the number of rows in `oauth_states`;
- sweep expired sessions periodically (today they are only removed when someone signs in);
- make sure the server has SQLite 3.35 or newer (the code uses `RETURNING`).
