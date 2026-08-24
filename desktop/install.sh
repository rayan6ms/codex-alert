#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lib_dir="${HOME}/.local/lib/codex-alert"
bin_dir="${HOME}/.local/bin"
config_dir="${HOME}/.config/codex-alert"
xdg_config_home="${XDG_CONFIG_HOME:-${HOME}/.config}"
xdg_data_home="${XDG_DATA_HOME:-${HOME}/.local/share}"
systemd_dir="${xdg_config_home}/systemd/user"
autostart_dir="${xdg_config_home}/autostart"
icon_dir="${xdg_data_home}/icons/hicolor/scalable/apps"
applications_dir="${xdg_data_home}/applications"

missing=()
for command in python3 notify-send install ln mktemp sed; do
    command -v "${command}" >/dev/null 2>&1 || missing+=("${command}")
done
if (( ${#missing[@]} )); then
    printf 'Missing required command(s): %s\n' "${missing[*]}" >&2
    printf 'Fedora: sudo dnf install python3 libnotify\n' >&2
    printf 'Ubuntu/Debian: sudo apt install python3 libnotify-bin\n' >&2
    printf 'Arch: sudo pacman -S python libnotify\n' >&2
    printf 'openSUSE: sudo zypper install python3 libnotify-tools\n' >&2
    exit 1
fi

systemd_user=false
if command -v systemctl >/dev/null 2>&1 \
        && systemctl --user show-environment >/dev/null 2>&1; then
    systemd_user=true
fi

install -d -m 700 \
    "${lib_dir}" \
    "${bin_dir}" \
    "${config_dir}" \
    "${HOME}/.local/state/codex-notify" \
    "${icon_dir}" \
    "${applications_dir}"

for program in codex-alert codex-notify-stop codex-notify-stop-desktop codex-phone-deliver; do
    install -m 700 "${project_dir}/desktop/${program}" "${lib_dir}/${program}"
    ln -sfn "${lib_dir}/${program}" "${bin_dir}/${program}"
done
install -m 600 "${project_dir}/desktop/codex_alert_common.py" "${lib_dir}/codex_alert_common.py"
install -m 644 "${project_dir}/desktop/dev.rayan.codexalert.svg" \
    "${icon_dir}/dev.rayan.codexalert.svg"
install -m 644 "${project_dir}/desktop/dev.rayan.codexalert.desktop" \
    "${applications_dir}/dev.rayan.codexalert.desktop"

if [[ "${systemd_user}" == true ]]; then
    install -d -m 700 "${systemd_dir}"
    install -m 600 "${project_dir}/desktop/codex-phone-delivery.service" \
        "${systemd_dir}/codex-phone-delivery.service"
    install -m 600 "${project_dir}/desktop/codex-phone-clear-on-input.service" \
        "${systemd_dir}/codex-phone-clear-on-input.service"
    install -m 600 "${project_dir}/desktop/codex-alert-hooks.service" \
        "${systemd_dir}/codex-alert-hooks.service"
    install -m 600 "${project_dir}/desktop/codex-alert-hooks.timer" \
        "${systemd_dir}/codex-alert-hooks.timer"
    systemctl --user daemon-reload
    systemctl --user enable --now codex-alert-hooks.timer >/dev/null
    account_detection="systemd user timer"
else
    install -d -m 700 "${autostart_dir}"
    escaped_bin="${bin_dir//\\/\\\\}/codex-alert"
    escaped_bin="${escaped_bin//\"/\\\"}"
    escaped_bin="${escaped_bin//&/\\&}"
    escaped_bin="${escaped_bin//|/\\|}"
    generated_entry="$(mktemp)"
    sed "s|@CODEX_ALERT_BIN@|${escaped_bin}|g" \
        "${project_dir}/desktop/dev.rayan.codexalert-watch.desktop" > "${generated_entry}"
    install -m 600 "${generated_entry}" \
        "${autostart_dir}/dev.rayan.codexalert-watch.desktop"
    unlink "${generated_entry}"
    account_detection="cross-desktop XDG autostart"
fi
"${bin_dir}/codex-alert" setup

printf '\nCodex Alert desktop is installed.\n'
printf 'Account detection: %s.\n' "${account_detection}"
printf 'Run codex-alert test to check the desktop notification.\n'
printf 'For phone alerts, install the Android app and run codex-alert pair.\n'
