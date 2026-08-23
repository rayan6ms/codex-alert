#!/usr/bin/env bash
set -euo pipefail

repository="${CODEX_ALERT_REPOSITORY:-rayan6ms/codex-alert}"
release_base="https://github.com/${repository}/releases/latest/download"

if [[ "$(uname -s)" != "Linux" ]]; then
    printf 'Codex Alert desktop currently supports Linux and its standard notification service.\n' >&2
    exit 1
fi

missing=()
for command in curl tar awk mktemp find grep; do
    command -v "${command}" >/dev/null 2>&1 || missing+=("${command}")
done
if (( ${#missing[@]} )); then
    printf 'Missing required command(s): %s\n' "${missing[*]}" >&2
    exit 1
fi
if command -v sha256sum >/dev/null 2>&1; then
    checksum() { sha256sum "$1" | awk '{ print $1 }'; }
elif command -v shasum >/dev/null 2>&1; then
    checksum() { shasum -a 256 "$1" | awk '{ print $1 }'; }
else
    printf 'Missing required command: sha256sum or shasum.\n' >&2
    exit 1
fi

temporary_dir="$(mktemp -d)"
cleanup() {
    rm -rf -- "${temporary_dir}"
}
trap cleanup EXIT

archive="${temporary_dir}/codex-alert-desktop.tar.gz"
checksums="${temporary_dir}/SHA256SUMS"
curl --proto '=https' --tlsv1.2 -fsSL \
    "${release_base}/codex-alert-desktop.tar.gz" -o "${archive}"
curl --proto '=https' --tlsv1.2 -fsSL \
    "${release_base}/SHA256SUMS" -o "${checksums}"

expected="$(awk '$2 == "codex-alert-desktop.tar.gz" { print $1 }' "${checksums}")"
actual="$(checksum "${archive}")"
if [[ -z "${expected}" || "${actual}" != "${expected}" ]]; then
    printf 'Downloaded package failed checksum verification. Nothing was installed.\n' >&2
    exit 1
fi

if tar -tzf "${archive}" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    printf 'Downloaded package contains an unsafe path. Nothing was installed.\n' >&2
    exit 1
fi
tar -xzf "${archive}" -C "${temporary_dir}"
package_dir="$(find "${temporary_dir}" -mindepth 1 -maxdepth 1 -type d -name 'codex-alert-*' -print -quit)"
if [[ -z "${package_dir}" || ! -x "${package_dir}/install.sh" ]]; then
    printf 'Downloaded package has an unexpected layout. Nothing was installed.\n' >&2
    exit 1
fi

"${package_dir}/install.sh"
