#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lib_dir="${HOME}/.local/lib/codex-alert"
bin_dir="${HOME}/.local/bin"
config_dir="${HOME}/.config/codex-alert"
systemd_dir="${HOME}/.config/systemd/user"
icon_dir="${HOME}/.local/share/icons/hicolor/scalable/apps"

for command in python3 notify-send systemctl; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        printf 'Missing required command: %s\n' "${command}" >&2
        exit 1
    fi
done

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

# Preserve credentials from pre-1.0 private installations without placing
# device-specific material in the public package.
legacy_config="${HOME}/.config/codex-notify"
if [[ -f "${legacy_config}/phone-token" && ! -f "${config_dir}/phone-token" ]]; then
    install -m 600 "${legacy_config}/phone-token" "${config_dir}/phone-token"
fi
if [[ -f "${legacy_config}/phone-server-cert.pem" && ! -f "${config_dir}/phone-cert.pem" ]]; then
    install -m 600 "${legacy_config}/phone-server-cert.pem" "${config_dir}/phone-cert.pem"
fi

install -m 600 "${project_dir}/desktop/codex-phone-delivery.service" \
    "${systemd_dir}/codex-phone-delivery.service"
install -m 600 "${project_dir}/desktop/codex-alert-hooks.service" \
    "${systemd_dir}/codex-alert-hooks.service"
install -m 600 "${project_dir}/desktop/codex-alert-hooks.timer" \
    "${systemd_dir}/codex-alert-hooks.timer"

systemctl --user daemon-reload
systemctl --user enable --now codex-alert-hooks.timer >/dev/null
"${bin_dir}/codex-alert" setup --quiet

printf '\nCodex Alert desktop is installed.\n'
printf 'Desktop notifications now cover every detected Codex profile.\n'
printf 'Next: install the Android APK, open it, then run: codex-alert pair\n'
