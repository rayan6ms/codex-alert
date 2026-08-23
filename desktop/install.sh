#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lib_dir="${HOME}/.local/lib/codex-alert"
bin_dir="${HOME}/.local/bin"
config_dir="${HOME}/.config/codex-alert"
systemd_dir="${HOME}/.config/systemd/user"
icon_dir="${HOME}/.local/share/icons/hicolor/scalable/apps"

missing=()
for command in python3 notify-send systemctl install ln; do
    command -v "${command}" >/dev/null 2>&1 || missing+=("${command}")
done
if (( ${#missing[@]} )); then
    printf 'Missing required command(s): %s\n' "${missing[*]}" >&2
    printf 'Fedora: sudo dnf install python3 libnotify\n' >&2
    printf 'Ubuntu/Debian: sudo apt install python3 libnotify-bin\n' >&2
    exit 1
fi
if ! systemctl --user show-environment >/dev/null 2>&1; then
    printf 'A working systemd user session is required. Log into your desktop and try again.\n' >&2
    exit 1
fi

install -d -m 700 \
    "${lib_dir}" \
    "${bin_dir}" \
    "${config_dir}" \
    "${HOME}/.local/state/codex-notify" \
    "${systemd_dir}" \
    "${icon_dir}"

for program in codex-alert codex-notify-stop codex-notify-stop-desktop codex-phone-deliver; do
    install -m 700 "${project_dir}/desktop/${program}" "${lib_dir}/${program}"
    ln -sfn "${lib_dir}/${program}" "${bin_dir}/${program}"
done
install -m 600 "${project_dir}/desktop/codex_alert_common.py" "${lib_dir}/codex_alert_common.py"
install -m 644 "${project_dir}/desktop/dev.rayan.codexalert.svg" \
    "${icon_dir}/dev.rayan.codexalert.svg"

install -m 600 "${project_dir}/desktop/codex-phone-delivery.service" \
    "${systemd_dir}/codex-phone-delivery.service"
install -m 600 "${project_dir}/desktop/codex-alert-hooks.service" \
    "${systemd_dir}/codex-alert-hooks.service"
install -m 600 "${project_dir}/desktop/codex-alert-hooks.timer" \
    "${systemd_dir}/codex-alert-hooks.timer"

systemctl --user daemon-reload
systemctl --user enable --now codex-alert-hooks.timer >/dev/null
"${bin_dir}/codex-alert" setup

printf '\nCodex Alert desktop is installed.\n'
printf 'Run codex-alert test to check the desktop notification.\n'
printf 'For phone alerts, install the Android app and run codex-alert pair.\n'
