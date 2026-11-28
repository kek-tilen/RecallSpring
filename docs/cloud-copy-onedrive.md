# Cloud copy and Your cloud folder in OneDrive: the Microsoft app

Decided 2026-11-28. RecallSpring signs in to OneDrive with an app that whoever runs it registers once in their own
Microsoft Entra directory. Only the app's **Application (client) ID** goes into the server settings, never into Git.
There is no client secret: RecallSpring is a public client and signs in with a code, like Google.

Without the ID, Settings › Data & backups › Cloud copy and Your cloud folder say that a Microsoft app ID is needed.

## Register the app (once)

Register it in a directory you own: your own Azure account or a Microsoft 365 developer tenant. Never register it in
a school's or employer's directory; the app belongs to whoever runs RecallSpring, not to an organisation whose
accounts sign in to it. Registering an app costs nothing, but making an Azure account may ask for a card to confirm
who you are.

1. Open the Microsoft Entra admin center (entra.microsoft.com) › **App registrations** › **New registration**.
2. Name it **RecallSpring**. OneDrive names the app folder after the app, so each account that connects gets
   `Apps › RecallSpring`, and RecallSpring can see nothing outside it.
3. **Supported account types:** *Accounts in any organizational directory and personal Microsoft accounts*. Leave
   the Redirect URI empty: RecallSpring does not use one.
4. **Authentication** › *Advanced settings*: set **Allow public client flows** to **Yes** (this is the code sign-in)
   and save. Do not make a client secret or certificate.
5. **API permissions** › *Add a permission* › Microsoft Graph › **Delegated permissions**: add only
   `Files.ReadWrite.AppFolder` and `offline_access`. Remove anything else listed (a new app lists `User.Read`;
   RecallSpring does not need it, so it never learns the name or email address of an account).
6. **Overview:** copy the **Application (client) ID**. Put it in `services/api/.env` on the computer RecallSpring
   runs on and restart the API and the worker:

   ```
   RS_CLOUD_ONEDRIVE_CLIENT_ID=<application (client) id>
   ```

## Connect

- **Cloud copy:** Settings › Data & backups: turn on **Encryption** first, then **Cloud copy › Connect › OneDrive**.
- **Your cloud folder:** Settings › Data & backups › **Your cloud folder › Connect › Connect OneDrive**. Each learner
  signs in with their own Microsoft account.

RecallSpring shows a code. On any device, open microsoft.com/devicelogin, sign in and enter the code; Microsoft asks
to let RecallSpring use only its own folder. The page continues by itself. If the code expires first, **Get a new
code**.

## Personal and school or work accounts

A personal Microsoft account works. A school or work account works only when its organisation allows it, and
RecallSpring says plainly when it does not:

- *Your school or work account does not allow this kind of sign-in*: the organisation blocks code sign-in.
- *Microsoft did not allow RecallSpring*: the sign-in was declined, or the organisation lets only its administrator
  allow new apps (Microsoft then asks for an administrator's approval).
- *This school or work account does not let RecallSpring use its own folder in OneDrive*: the sign-in worked, but
  OneDrive for work or school refused the app folder. RecallSpring never asks for wider access instead.

In each case nothing is connected; use a personal Microsoft account, Google Drive or Dropbox. Microsoft's own
documentation is not clear on app folders for work or school accounts, so this is checked with a real account only
when one connects.

## What RecallSpring can see

Only its own app folder, `OneDrive › Apps › RecallSpring`:

- `Backups`: the encrypted backups (Cloud copy), in the same layout as the local backup folder.
- `Material`: a learner's readable copy by course (Your cloud folder), with `Material › Exports` for exports sent
  there.

And how much room is free, which Settings shows. Nothing else in the OneDrive, no account name and no email address.
Names OneDrive does not accept (such as `:` or `?` in a name, or `CON`) are made safe with `_`; a second file whose
name differs only in letter case gets " 1". Large files go up in 10 MiB pieces that resume after a dropped
connection.

## Staying signed in and disconnecting

Microsoft gives a new refresh token on each use; RecallSpring keeps the newest in `secrets_dir` (DPAPI on Windows,
0600 elsewhere), never in the database, a backup, logs or the browser. A sign-in unused for about 90 days expires,
and Today then says OneDrive no longer allows RecallSpring and offers to sign in again.

Microsoft has no call an app can use to withdraw its own sign-in, so **Disconnect** makes RecallSpring forget it. To
withdraw it at Microsoft as well, remove RecallSpring from the apps that can use your account (for a personal
account at account.live.com/consent/Manage; for a school or work account at myapps.microsoft.com, where the
organisation allows it, or ask its administrator).

Only one provider at a time: to move from Google Drive or Dropbox to OneDrive (or back), disconnect first. Details
and the rest of the behaviour: docs/08 → Cloud copy and Your cloud folder.
