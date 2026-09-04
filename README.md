# Codex Alert

Receive a clean Linux desktop and Android notification when Codex finishes or
fails. It works with every authenticated local Codex account and sends directly
over your LAN; there is no cloud relay.

## 1. Install on the computer

Run one command in a terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/rayan6ms/codex-alert/main/install-latest.sh | bash
```

The script checks the system first, downloads the latest release into a
temporary directory, verifies its checksum, installs it for the current user,
and removes the temporary files. It never uses `sudo`.

Codex Alert detects accounts by Codex's `auth.json` marker, preserves unrelated
hooks, preserves T3 Code's shared shadow-home symlinks, and automatically
notices newly added accounts. It also revalidates its completion hook after a
Codex upgrade changes the hook's trust identity.

Desktop alerts use the standard [freedesktop.org notification service](https://specifications.freedesktop.org/notification/latest/),
so the same installer works on GNOME, KDE Plasma, Xfce, Cinnamon, MATE, LXQt,
Budgie, and other compatible X11 or Wayland desktops. No desktop extension is
needed. A systemd user timer is used when available; other Linux systems use
the standard [XDG autostart mechanism](https://specifications.freedesktop.org/autostart/latest/) instead.
Completion alerts use a normal, non-transient notification so the banner is
visible reliably on GNOME and other desktop environments. The latest
completion replaces the previous Codex Alert entry, keeping the notification
tray useful instead of accumulating stale completion banners.
The Codex/OpenAI icon is supplied directly to the notification service so it
does not depend on desktop-entry app registration.

Check the result with:

```sh
codex-alert test
```

## 2. Add the phone

1. Install [Codex Alert for Android](https://github.com/rayan6ms/codex-alert/releases/latest/download/codex-alert.apk)
   and open it. Android may ask you to allow installs from your browser.
2. Follow the app's three-screen setup: allow notifications, create a pairing
   code, and finish the connection check.
3. When prompted, run `codex-alert pair` on the computer. Enter the code and
   confirm that the security code shown on both devices is identical.

After setup, the installation steps disappear. The app opens to a status
dashboard that clearly shows whether the receiver, notifications, and secure
computer pairing are working, along with the most recently received alert.
The dashboard's READY indicator is based on the receiver's live listening
socket, not a stale saved status. Use the refresh icon beside it to restart
the receiver check; the control is disabled while that check is in progress.
Use the theme button at the right side of the app header to switch between
light and dark mode. The dashboard keeps the five most recent Codex
alerts on-device, with previous and next buttons below the alert card.

Codex Alert ignores ephemeral `codex exec` helpers used by T3 Code to generate
thread titles and other metadata. Completion IDs are claimed before either
desktop or phone delivery starts, while both receivers retain their own
idempotency checks as an additional safeguard against duplicate Stop hooks.
Terminal task failures are detected from Codex's append-only rollout events,
because Codex does not currently run Stop hooks for failed turns. The watcher
alerts only on a turn-level `task_complete` error: failed commands that Codex
can recover from, cancelled turns, subagents, and ephemeral metadata jobs do
not trigger an alert. It follows new data through Linux inotify and keeps
durable byte offsets, so it is immediate without repeatedly reading session
history or replaying old failures after an install or restart.

On GNOME, a phone alert is also dismissed after the first new keyboard or
pointer activity on the paired desktop following that completion. This uses
GNOME's session idle timer: Codex Alert sees only an elapsed-time value, never
the key pressed, button clicked, or pointer position.

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
