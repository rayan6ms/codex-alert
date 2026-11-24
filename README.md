# Agents Alert

Receive Linux desktop and Android notifications when a coding agent finishes,
fails, or asks for input. Agents Alert supports Codex, Claude Code, and Google
Antigravity. Alerts travel directly to your phone over your LAN.

## 1. Install on the computer

Run one command in a terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/rayan6ms/codex-alert/main/install-latest.sh | bash
```

The script checks the system first, downloads the latest release into a
temporary directory, verifies its checksum, installs it for the current user,
and removes the temporary files. It never uses `sudo`.

Agents Alert detects Codex accounts by the `auth.json` marker and installs
hooks for detected Claude Code and Antigravity installations. It preserves
unrelated hooks and T3 Code's shared shadow-home symlinks. It also revalidates
the completion hook after Codex upgrades.

To register hooks for a provider outside your usual install location, run
`agents-alert setup --provider claude-code` or
`agents-alert setup --provider antigravity`. Claude Code supports
`CLAUDE_CONFIG_DIR` for a custom settings directory. Antigravity App, CLI,
and IDE use the shared `~/.gemini/config/hooks.json` file. [Claude Code hooks](https://code.claude.com/docs/en/hooks) · [Antigravity hooks](https://antigravity.google/docs/hooks)

Desktop alerts use the standard [freedesktop.org notification service](https://specifications.freedesktop.org/notification/latest/),
so the same installer works on GNOME, KDE Plasma, Xfce, Cinnamon, MATE, LXQt,
Budgie, and other compatible X11 or Wayland desktops. No desktop extension is
needed. A systemd user timer is used when available; other Linux systems use
the standard [XDG autostart mechanism](https://specifications.freedesktop.org/autostart/latest/) instead.
Completion alerts use a normal, non-transient notification so the banner is
visible reliably on GNOME and other desktop environments. The latest
alert replaces the previous Agents Alert entry, keeping the notification
tray useful instead of accumulating stale completion banners.
The app icon is supplied directly to the notification service so it
does not depend on desktop-entry app registration.

Check the result with:

```sh
agents-alert test
```

## 2. Add the phone

1. Install [Agents Alert for Android](https://github.com/rayan6ms/codex-alert/releases/latest/download/codex-alert.apk)
   and open it. Android may ask you to allow installs from your browser.
2. Follow the app's three-screen setup: allow notifications, create a pairing
   code, and finish the connection check.
3. When prompted, run `agents-alert pair` on the computer. Enter the code and
   confirm that the security code shown on both devices is identical.

After setup, the installation steps disappear. The app opens to a status
dashboard that clearly shows whether the receiver, notifications, and secure
computer pairing are working, along with the most recently received alert.
The dashboard's READY indicator is based on the receiver's live listening
socket, not a stale saved status. Use the refresh icon beside it to restart
the receiver check; the control is disabled while that check is in progress.
Use the theme button at the right side of the app header to switch between
light and dark mode. The dashboard keeps the five most recent
alerts on-device, with previous and next buttons below the alert card.

Agents Alert ignores ephemeral `codex exec` helpers used by T3 Code to generate
thread titles and other metadata. Completion IDs are claimed before either
desktop or phone delivery starts, while both receivers retain their own
idempotency checks as an additional safeguard against duplicate Stop hooks.
The watcher detects terminal Codex failures from failed `task_complete`
events in the rollout log. Failed commands that Codex can recover from,
cancelled turns, subagents, and ephemeral metadata jobs do not trigger an alert.
The watcher follows new data through Linux inotify and keeps
durable byte offsets, so it is immediate without repeatedly reading session
history or replaying old failures after an install or restart.
On every watcher start, existing files are baselined at their current end;
events from while the watcher was offline are intentionally skipped. Replaced
or truncated logs are also baselined, and events older than two minutes are
discarded to prevent stale notification bursts.

Explicit Codex `request_user_input`, `request_user_input_async`, and
`send_message_to_user_async` tool calls send an “Input ℹ️” notification with
the question or message. Each request has its own notification ID.
Ordinary questions written in assistant prose do not trigger this alert.

Claude Code alerts cover completed responses, terminal API errors, questions,
and tool approval requests. Antigravity alerts cover completed executions,
terminal errors or step limits, and questions raised through `ask_question`.

With T3 Code integration enabled, the watcher follows T3 Code's own run status
and pending requests in the local T3 Code database for every provider T3 Code
runs (Codex, Antigravity, Claude Code, OpenCode, Cursor, and any future
provider). Completed runs, failed runs, and pending user questions, approval
prompts, or secret requests all alert from T3 Code's state, while native hooks
continue handling standalone CLI and IDE sessions outside T3 Code. Notifications
use the thread title when available (from T3 Code or Codex's session index),
falling back to the project name instead of scratch directory slugs.

On GNOME, a phone alert is also dismissed after the first new keyboard or
pointer activity on the paired desktop following that completion. This uses
GNOME's session idle timer: Agents Alert sees only an elapsed-time value, never
the key pressed, button clicked, or pointer position.

Pair while both devices are on the same trusted Wi-Fi network. The app guides
you to battery settings only if your phone restricts background delivery.

Want alerts outside your home network? Turn on Tailscale on both devices
(before or after pairing). Agents Alert automatically discovers your paired
Android device over Tailscale, verifies it against the pinned certificate and
token, and remembers its Tailscale address. It is optional; no port forwarding
is needed.

## Optional T3 Code integration

Run `agents-alert t3 on` to enable alerts from the local T3 Code database.
Enable the matching option in Android to open the exact T3 thread from a
notification. Android asks for Usage Access when you enable automatic clearing
when T3 opens.

## Useful commands

```sh
agents-alert status   # accounts, phone, and delivery state
agents-alert test     # test desktop and phone notifications
agents-alert setup    # configure hooks for installed agents
```

Run the install command again to update. The original `codex-alert` command
is an alias, and existing Android installs retain their pairing and history.
Pairing credentials remain on the computer in `~/.config/codex-alert/` with
user-only permissions. Use **Forget
paired computer** in the Android app to revoke them.

Source releases include SHA-256 checksums and GitHub artifact attestations.
See [SECURITY.md](SECURITY.md) and the [MIT License](LICENSE).
