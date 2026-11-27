# Cloud copy to Google Drive: the Google app

Decided 2026-11-27. RecallSpring signs in to Google Drive with an app that whoever runs it registers once. The app's
ID and secret go into the server settings, never into Git. Google treats this kind of app as one that cannot keep a
secret, so the "secret" names the app and protects nothing of yours; it still stays out of the repository.

Without these settings, Settings › Data & backups › Cloud copy says that a Google app ID is needed.

## Register the app (once)

1. Open the Google Cloud console (console.cloud.google.com) with the Google account that will own the app and create
   a project, for example "RecallSpring".
2. **APIs & Services › Library:** enable the **Google Drive API**.
3. **Google Auth Platform › Branding** (OAuth consent screen): app name "RecallSpring", a support email, audience
   **External**. Under **Data access** add only the scope `https://www.googleapis.com/auth/drive.file` ("See, edit,
   create and delete only the specific Google Drive files you use with this app"). It is a non-sensitive scope, so no
   app verification is needed. Then **Audience › Publish app** (status *In production*). This matters: while an
   External app is in *Testing*, Google lets its sign-ins expire after 7 days, so the daily copy would stop with
   "Google Drive no longer allows RecallSpring" a week after connecting. (In *Testing* only accounts listed under
   Test users can sign in at all. A name and logo on the consent screen need Google's lighter brand verification.)
4. **Clients › Create client:** application type **TVs and Limited Input devices**, a name such as "RecallSpring
   server". Copy the client ID and the client secret.
5. Put them in `services/api/.env` on the computer RecallSpring runs on and restart the API and the worker:

   ```
   RS_CLOUD_GOOGLE_CLIENT_ID=<id>.apps.googleusercontent.com
   RS_CLOUD_GOOGLE_CLIENT_SECRET=<the client secret>
   ```

## Connect

Settings › Data & backups: turn on **Encryption** first, then **Cloud copy › Connect › Google Drive**. Open the
address shown (google.com/device) on any device, sign in, type the code, and allow RecallSpring to use only the files
it creates. The page continues by itself; the first copy starts at once.

## What RecallSpring can see

Only the files it created: the folder `My Drive › RecallSpring backups` and what is in it. Nothing else in the Drive,
no account name and no email address. Details and the rest of the behaviour: docs/08 → Cloud copy.
