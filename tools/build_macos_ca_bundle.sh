#!/bin/bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <output-pem>" >&2
  exit 2
fi

OUTPUT="$1"
mkdir -p "$(dirname "$OUTPUT")"
TMP="$(mktemp "${OUTPUT}.XXXXXX")"
trap 'rm -f "$TMP"' EXIT
: > "$TMP"
chmod 600 "$TMP"

append_pem_file() {
  local candidate="$1"
  [[ -n "$candidate" && -r "$candidate" ]] || return 0
  # Avoid self-inclusion, which would grow the bundle on every reinstall.
  if [[ "$candidate" -ef "$OUTPUT" || "$candidate" -ef "$TMP" ]]; then
    return 0
  fi
  cat "$candidate" >> "$TMP"
  printf '\n' >> "$TMP"
}

# Standard macOS/OpenSSL bundle, if available.
append_pem_file /etc/ssl/cert.pem

# Include Apple's published system-root certificates in the extra bundle.
# Do not dump all certificates from mutable system/login keychains here: that
# would turn certificates into trust anchors regardless of their trust settings.
# The launcher also uses Bun's --use-system-ca flag to honor macOS system trust.
SYSTEM_ROOTS="/System/Library/Keychains/SystemRootCertificates.keychain"
if [[ -r "$SYSTEM_ROOTS" ]] && command -v security >/dev/null 2>&1; then
  security find-certificate -a -p "$SYSTEM_ROOTS" >> "$TMP" 2>/dev/null || true
  printf '\n' >> "$TMP"
fi

# Optional organization TLS-inspection root, exported by an administrator as PEM.
# Fail early on a typo instead of silently creating a bundle that still cannot trust it.
if [[ -n "${CERGEA_EXTRA_CA_CERT:-}" ]]; then
  if [[ ! -f "$CERGEA_EXTRA_CA_CERT" || ! -r "$CERGEA_EXTRA_CA_CERT" ]]; then
    echo "CERGEA_EXTRA_CA_CERT is not a readable file: $CERGEA_EXTRA_CA_CERT" >&2
    exit 1
  fi
  if ! grep -q -- '-----BEGIN CERTIFICATE-----' "$CERGEA_EXTRA_CA_CERT"; then
    echo "CERGEA_EXTRA_CA_CERT is not PEM-encoded certificate data: $CERGEA_EXTRA_CA_CERT" >&2
    exit 1
  fi
  append_pem_file "$CERGEA_EXTRA_CA_CERT"
fi

# Honor any caller-provided CA bundles in addition to the macOS store.
append_pem_file "${NODE_EXTRA_CA_CERTS:-}"
append_pem_file "${SSL_CERT_FILE:-}"

if ! grep -q -- '-----BEGIN CERTIFICATE-----' "$TMP"; then
  echo "Could not build a CA bundle from macOS certificates." >&2
  echo "Ensure the macOS keychains are readable and retry." >&2
  exit 1
fi
chmod 600 "$TMP"
mv -f "$TMP" "$OUTPUT"
trap - EXIT
printf 'Built macOS CA trust bundle: %s\n' "$OUTPUT"
