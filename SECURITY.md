# Security

Codex Alert has no cloud relay. The Android receiver accepts only local/private
LAN and Tailscale sources, uses a device-generated Android Keystore TLS key, and
requires a random bearer token after pairing. Pair only on a trusted network and
confirm that the four-part security code is identical on the phone and desktop.

Credentials are stored in Android private app data and in
`~/.config/codex-alert/` with user-only permissions. Use **Forget paired
computer** in the app to rotate the token immediately.

Please report vulnerabilities privately through GitHub's security advisory
form rather than a public issue.
