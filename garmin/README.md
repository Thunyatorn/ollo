# ollo on a Garmin watch

A Connect IQ watch app that works as the caregiver's wrist buzzer:

- vibrates when an alert needs you: long pulses for **high**, short for **medium** (the same patterns as the ESP32 buzzer),
  again every 10 s (high) or 20 s (medium) until someone has it
- shows what and where ("Possible fall", "Child 7 - Stairs") and what happens next ("Backup is called in 12s")
- **START** (or a tap): *I'm on it*. **Hold UP** (menu): *I'm on it* or *I can't respond*. **UP/DOWN**: other open alerts
- records the acknowledgement as `via watch` for the paired caregiver

How it connects: watch → Garmin Connect app on the phone (Bluetooth) → the internet → the worker's public https address
(the ngrok address in `PUBLIC_BASE_URL`) → `GET /watch/state` and `POST /watch/act`. The watch sends a pairing code, never a
password. Only the code's hash is kept by the worker (`worker/.watch-keys.json`, git-ignored).

**Limit:** Garmin lets a third-party app run in real time only while it is open. Keep ollo open on the watch during a shift
(it checks every 3 s). Closed, a background check runs at most every 5 minutes and, if an alert is waiting, asks the watch to
open ollo. Instant alerts with the app closed would need a native phone companion app.

## 1. Pair the watch (on the computer)

1. Start the worker, and ngrok with the address in `worker/.env` (`PUBLIC_BASE_URL`).
2. Dashboard › **Settings › Garmin watch** › **Pair my watch**. It shows a code like `K7Q4M-2XDPA` and the server address.
   A new code replaces the old one, so a lost watch can be cut off by pairing again.

## 2. Install Garmin's tools (once, about 15 minutes)

1. Download the **Connect IQ SDK Manager**: https://developer.garmin.com/connect-iq/sdk/
2. Open it and **sign in with your Garmin account** (do this yourself; the build never needs your password).
3. Download the latest **SDK**, then under **Devices** download your watch model.
4. Optional: in VS Code install the **Monkey C** extension (syntax and a simulator button).

## 3. Build and install

```bash
garmin/build.sh fr265 --code K7Q4M-2XDPA --sim     # fr265 = your watch's product id; --sim opens Garmin's simulator
garmin/build.sh fr265 --code K7Q4M-2XDPA           # just build garmin/bin/ollo-fr265.prg
```

- The server address is read from `worker/.env` (or pass `--server https://...`). It must be https.
- The code and address are baked into a temporary copy of the project, never into git.
- The first build makes `garmin/developer_key.der` (git-ignored). Keep it: it signs your builds.
- Your model must be in `garmin/ollo/manifest.xml`. Listed: epix2, fenix7/7s/7x, fr255, fr265, fr955, fr965, venu2/2s,
  venu3, vivoactive4/5. To add yours, copy its id from the SDK Manager's device list into a new `<iq:product id="..."/>` line.

**Install on the watch:** connect it by USB and copy `garmin/bin/ollo-<model>.prg` into the `GARMIN/APPS` folder (on a Mac
the watch shows up with [OpenMTP](https://openmtp.ganeshrvel.com/) or Garmin Express). Unplug; ollo appears in the apps list.

A sideloaded app cannot be configured from the Garmin Connect phone app, which is why the build bakes the code in. If the
code changes, build again. (An app published as a private beta in the Connect IQ store can be set up in Garmin Connect instead:
its two settings, server address and pairing code, are already defined.)

## What was tested

- The worker side (pairing, `/watch/state`, `/watch/act`, wrong codes, rate limit) by unit tests, and through the real public
  ngrok address with `worker/scripts/fake_watch.py`, which sends exactly the watch's requests. The alert was acknowledged
  `via watch`.
- **The Monkey C app itself has not been compiled yet**: the Connect IQ SDK needs your Garmin sign-in. Expect a first round of
  small compile fixes on the first `build.sh` run.

## Files

| File | What |
| --- | --- |
| `ollo/source/OlloApp.mc` | app entry; registers the 5-minute background check |
| `ollo/source/OlloClient.mc` | checks every 3 s, buzzes, sends "I'm on it" / "I can't respond" |
| `ollo/source/OlloView.mc` | the screen |
| `ollo/source/OlloDelegate.mc` | buttons and the menu |
| `ollo/source/OlloBackground.mc` | the check while ollo is closed |
| `ollo/source/OlloConfig.mc` | the two settings and request headers |
| `build.sh` | build (and simulator) with your settings baked in |
