#!/usr/bin/env bash
set -euo pipefail

# Development convenience only. Release users install the APK downloaded from
# GitHub and do not need ADB, root, Termux, or a USB connection for pairing.
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_apk="${project_dir}/app/build/outputs/apk/release/app-release.apk"
debug_apk="${project_dir}/app/build/outputs/apk/debug/app-debug.apk"
apk="${release_apk}"
[[ -f "${apk}" ]] || apk="${debug_apk}"

if [[ ! -f "${apk}" ]]; then
    printf 'Build the APK first with ./gradlew assembleDebug or assembleRelease.\n' >&2
    exit 1
fi

mapfile -t devices < <(adb devices | awk 'NR > 1 && $2 == "device" { print $1 }')
if (( ${#devices[@]} != 1 )); then
    printf 'Expected exactly one authorized ADB device; found %d.\n' "${#devices[@]}" >&2
    exit 1
fi

serial="${devices[0]}"
if ! install_output="$(adb -s "${serial}" install -r "${apk}" 2>&1)"; then
    printf '%s\n' "${install_output}" >&2
    if [[ "${install_output}" != *"INSTALL_FAILED_USER_RESTRICTED"* ]] || \
       ! adb -s "${serial}" shell 'su -c "id"' >/dev/null 2>&1; then
        exit 1
    fi
    remote_apk=/data/local/tmp/codex-alert.apk
    adb -s "${serial}" push "${apk}" "${remote_apk}" >/dev/null
    adb -s "${serial}" shell "su -c 'pm install -r ${remote_apk}'"
    adb -s "${serial}" shell "rm -f ${remote_apk}" >/dev/null 2>&1 || true
else
    printf '%s\n' "${install_output}"
fi

adb -s "${serial}" shell am start -n dev.rayan.codexalert/.MainActivity >/dev/null
printf 'Installed Codex Alert. Pair it from the app; runtime does not use ADB.\n'
