# Cloud copy and Your cloud folder in Dropbox: the Dropbox app

Decided 2026-11-28. RecallSpring signs in to Dropbox with an app that whoever runs it registers once. Only the app's
**App key** goes into the server settings, never into Git. There is no app secret: RecallSpring signs in with PKCE,
the way Dropbox recommends for apps that cannot keep a secret.

Without the key, Settings › Data & backups › Cloud copy and Your cloud folder say that a Dropbox App key is needed.

## Register the app (once)

1. Open the Dropbox App Console (www.dropbox.com/developers/apps) with the Dropbox account that will own the app and
   choose **Create app**.
2. **Scoped access**, then **App folder** (not Full Dropbox). Name it **RecallSpring**. Dropbox makes the folder
   `Apps › RecallSpring` in each account that connects, and RecallSpring can see nothing outside it.
3. **Permissions** tab: tick only `files.metadata.read` and `files.content.write`, then **Submit**. RecallSpring does
   not ask for `account_info.read`, so it never learns the name or email address of an account, and it cannot show
   how much room is free. A full Dropbox is reported when an upload fails ("Your Dropbox is full").
4. **Settings** tab: leave the Redirect URIs empty. RecallSpring does not use one: Dropbox shows a code that the
   learner pastes back into RecallSpring. Copy the **App key**. You do not need the App secret.
5. Put the key in `services/api/.env` on the computer RecallSpring runs on and restart the API and the worker:

   ```
   RS_CLOUD_DROPBOX_APP_KEY=<app key>
   ```

A new Dropbox app is in *Development*: up to 500 Dropbox accounts can connect. Once 50 have connected, Dropbox gives
two weeks to apply for *Production* in the App Console; for one household or a small group, Development is enough.

## Connect

- **Cloud copy:** Settings › Data & backups: turn on **Encryption** first, then **Cloud copy › Connect › Dropbox**.
- **Your cloud folder:** Settings › Data & backups › **Your cloud folder › Connect › Connect Dropbox**. Each learner
  signs in with their own Dropbox account.

Choose **Open Dropbox**, allow RecallSpring, copy the code Dropbox shows, paste it into RecallSpring and choose
**Connect**. The code works once and only within 30 minutes; after that, **Start again**.

## What RecallSpring can see

Only its own app folder, `Dropbox › Apps › RecallSpring`:

- `Backups`: the encrypted backups (Cloud copy), in the same layout as the local backup folder.
- `Material`: a learner's readable copy by course (Your cloud folder), with `Material › Exports` for exports sent
  there.

Nothing else in the Dropbox, no account name and no email address. Only one provider at a time: to move from Google
Drive to Dropbox (or back), disconnect first. Details and the rest of the behaviour: docs/08 → Cloud copy and Your
cloud folder.
