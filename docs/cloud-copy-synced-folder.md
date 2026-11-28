# Cloud copy and Your cloud folder in a synced folder: iCloud Drive and other sync apps

Decided 2026-11-28. iCloud Drive gives a server no way to put files in it. What works is the folder its app keeps
in sync, so RecallSpring offers one general choice, **A synced folder**: it writes into a folder on the computer it
runs on, and the sync app uploads it. The same works with iCloud Drive, Proton Drive, Nextcloud, Syncthing, pCloud,
a network drive, or the desktop apps of Dropbox, OneDrive and Google Drive.

There is no sign-in, no app to register and nothing secret to keep.

## What it needs

- RecallSpring runs on a computer where the sync app runs, as the same user. iCloud Drive: Windows (iCloud for
  Windows, folder `iCloudDrive` in your home folder) or a Mac (`Library/Mobile Documents/com~apple~CloudDocs`).
  There is no iCloud Drive app for Linux, so a Linux server can use Syncthing or Nextcloud, not iCloud.
- The folder above the one RecallSpring uses must exist. RecallSpring makes only its own last folder, so when the
  sync folder or a network drive is missing, nothing is written to the local disk instead.

## Cloud copy

Only the first account, because a backup holds the whole installation. Settings › Data & backups: turn on
**Encryption** first, then **Cloud copy › Connect › A synced folder**. Folders that sync apps usually make are
offered (**Use** fills in, for example, `…\iCloudDrive\RecallSpring backups`); any other folder can be pasted.
**Check folder** shows whether RecallSpring can write there, how much room is free on that disk and which sync app
it recognised; then **Use this folder**.

The local backup folder stays the main copy. The synced folder gets the encrypted backups in the same layout as the
local folder, after every backup, and loses what the local folder removed. A copy downloaded from icloud.com (or
another sync app) restores with `recallspring backup-restore --from <folder> --key <key file>`.

## Your cloud folder

The first account chooses one folder for everyone: Settings › Data & backups › **Your cloud folder › Connect ›
Choose a synced folder**. Each learner who chooses **Use a synced folder** gets a subfolder of their own, named by
their sign-in name (`RecallSpring › maja › <course>`). Two learners never share one: a name that differs only in
letter case is numbered (`Maja (1)`).

The folder syncs to the account of whoever runs RecallSpring, not to the learners' own accounts. Settings tells both
sides so. **Stop offering the synced folder** removes the choice; learners already using it keep their files, and
their copying stops with a plain message.

## What RecallSpring can and cannot see

- It sees what it wrote into the folder: each file is written as a hidden `.recallspring-….part` file and renamed
  when complete, so a sync app never uploads half a file, and its size is read back.
- It cannot see when the sync app has uploaded a file, or whether the sync app is signed in. Look at icloud.com (or
  the sync app) now and then. Settings says "Handed to iCloud Drive", not "copied to iCloud".
- When the folder is gone (the sync app signed out, a drive not connected), Today says so at once and RecallSpring
  tries again later.

## Server settings

With `RS_BACKUP_SETTINGS_FROM_WEB=false` (a hosted server) nothing about backups can be changed in Settings, so the
folders come from the server settings instead. `RS_CLOUD_FOLDER_DIR` turns the cloud copy on by itself once
encryption is on (Settings shows it, with "set in the server settings"); remove it to stop the copy.

```
RS_CLOUD_FOLDER_DIR=<folder for the encrypted cloud copy>
RS_DRIVE_FOLDER_DIR=<folder holding a subfolder per learner>
```

Details and the rest of the behaviour: docs/08 → Cloud copy and Your cloud folder.
