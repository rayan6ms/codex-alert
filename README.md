# Codex Alert

Receive a clean GNOME and Android notification when Codex finishes. It works
with every authenticated local Codex account and sends directly over your LAN;
there is no cloud relay.

## 1. Install on the computer

Run one command in a terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/rayan6ms/codex-alert/main/install-latest.sh | bash
```

The script checks the system first, downloads the latest release into a
temporary directory, verifies its checksum, installs it for the current user,
and removes the temporary files. It never uses `sudo`.

Codex Alert detects accounts by Codex's `auth.json` marker, preserves unrelated
hooks, and automatically notices accounts added or removed later. GNOME's native
notification service is used, so no Shell extension is needed.

Check the result with:

```sh
codex-alert test
```

## 2. Add the phone

1. Install [Codex Alert for Android](https://github.com/rayan6ms/codex-alert/releases/latest/download/codex-alert.apk)
   and open it. Android may ask you to allow installs from your browser.
2. Allow notifications, then tap **Create 8-digit pairing code**.
3. On the computer, run `codex-alert pair`. Enter the code and confirm that the
   security code shown on both devices is identical.

Pair while both devices are on the same trusted Wi-Fi network. The app guides
you to battery settings only if your phone restricts background delivery.

Want alerts outside your home network? Turn on Tailscale on both devices before
pairing. It is optional; no port forwarding is needed.

## Optional T3 Code integration

T3 Code support is off by default. To make notification taps open the exact T3
thread, run `codex-alert t3 on` and enable the matching option in the Android
app. Android Usage Access is requested only if you also enable automatic
clearing when T3 opens.

## Useful commands

```sh
codex-alert status   # accounts, phone, and delivery state
codex-alert test     # test desktop and phone notifications
codex-alert setup    # rescan accounts immediately
```

Run the install command again to update. Pairing credentials remain on the
computer in `~/.config/codex-alert/` with user-only permissions. Use **Forget
paired computer** in the Android app to revoke them.

Source releases include SHA-256 checksums and GitHub artifact attestations.
See [SECURITY.md](SECURITY.md) and the [MIT License](LICENSE).
