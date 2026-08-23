# Codex Alert

Get a clean desktop and Android notification whenever Codex finishes. Codex
Alert works with every local `~/.codex*` account, uses your LAN or Tailscale,
and has no cloud relay.

The Linux companion uses GNOME's native notification service, so there is no
version-sensitive GNOME Shell extension to install. New Codex profiles are
detected automatically. T3 Code integration is optional and off by default.

## Install

### 1. Install the desktop companion

You need GNOME Linux, Python 3, `notify-send`, and a systemd user session.

```sh
mkdir -p ~/Downloads/codex-alert-install
cd ~/Downloads/codex-alert-install
curl -fL https://github.com/rayan6ms/codex-alert/releases/latest/download/codex-alert-desktop.tar.gz -o codex-alert-desktop.tar.gz
tar -xzf codex-alert-desktop.tar.gz
cd codex-alert-*/
./install.sh
```

The installer preserves other hooks and configures every detected Codex
account. It also checks for new accounts every five minutes.

### 2. Install the Android app

On your phone, download [codex-alert.apk](https://github.com/rayan6ms/codex-alert/releases/latest/download/codex-alert.apk),
allow your browser to install unknown apps if Android asks, and open **Codex
Alert**.

In the app, follow the numbered steps:

1. Allow notifications.
2. Tap **Create 8-digit pairing code**.
3. On the computer, run `codex-alert pair`.
4. Enter the phone's code and confirm that both security codes match.
5. Keep the app's receiver enabled and send the offered test notification.

Pair on the same trusted Wi-Fi network. Codex Alert discovers the phone
automatically; if discovery is unavailable, enter one of the addresses shown in
the app. For delivery away from home, enable Tailscale on both devices before
pairing. No USB, ADB, root, Termux, or port forwarding is required.

Some Android vendors restrict background apps. If alerts arrive late, use the
app's **Battery/background settings** button and allow unrestricted battery use
or autostart for Codex Alert.

## Optional T3 Code integration

Enable it only if you want notification taps to open the exact T3 Code thread:

```sh
codex-alert t3 on
```

Then enable **Open exact T3 Code thread** in the Android app. The separate
auto-clear option needs Android Usage Access; the app links to that permission
only when you enable the feature. Disable desktop routing with
`codex-alert t3 off`.

## Check or troubleshoot

```sh
codex-alert status
codex-alert test
codex-alert setup   # rescan Codex accounts now
```

The desktop stores private pairing material in `~/.config/codex-alert/` with
user-only permissions. **Forget paired computer** in the Android app rotates
the delivery token. Pairing codes expire after 10 minutes and five failed
attempts. See [SECURITY.md](SECURITY.md) for the security model.

To update, reinstall the latest desktop archive and APK. Android keeps the app's
settings when the signed APK is installed over an older release.

## Develop

Android builds use JDK 17 and Android SDK 35.

```sh
python3 -m unittest discover -s desktop/tests -v
./gradlew testDebugUnitTest lintDebug assembleDebug
./phone/install-via-adb.sh  # optional development convenience
```

Licensed under the [MIT License](LICENSE).
