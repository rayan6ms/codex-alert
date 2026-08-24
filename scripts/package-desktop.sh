#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="${1:-${project_dir}/dist}"
version="$(<"${project_dir}/VERSION")"
stage_dir="$(mktemp -d)"
package_dir="${stage_dir}/codex-alert-${version}"

cleanup() {
    rm -rf -- "${stage_dir}"
}
trap cleanup EXIT

install -d "${package_dir}/desktop"
install -m 755 "${project_dir}/install.sh" "${package_dir}/install.sh"
install -m 644 "${project_dir}/README.md" "${package_dir}/README.md"
install -m 644 "${project_dir}/SECURITY.md" "${package_dir}/SECURITY.md"
install -m 644 "${project_dir}/LICENSE" "${package_dir}/LICENSE"

for source in \
    codex-alert \
    codex-alert-hooks.service \
    codex-alert-hooks.timer \
    codex-notify-stop \
    codex-notify-stop-desktop \
    codex-phone-deliver \
    codex-phone-clear-on-input.service \
    codex-phone-delivery.service \
    codex_alert_common.py \
    dev.rayan.codexalert.svg \
    dev.rayan.codexalert.desktop \
    dev.rayan.codexalert-watch.desktop \
    install.sh; do
    install -m 644 "${project_dir}/desktop/${source}" "${package_dir}/desktop/${source}"
done
chmod 755 \
    "${package_dir}/desktop/codex-alert" \
    "${package_dir}/desktop/codex-notify-stop" \
    "${package_dir}/desktop/codex-notify-stop-desktop" \
    "${package_dir}/desktop/codex-phone-deliver" \
    "${package_dir}/desktop/install.sh"

install -d "${output_dir}"
tar \
    --sort=name \
    --mtime='UTC 1970-01-01' \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -C "${stage_dir}" \
    -czf "${output_dir}/codex-alert-desktop.tar.gz" \
    "codex-alert-${version}"
