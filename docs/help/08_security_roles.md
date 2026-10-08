# Security & Roles

- **Supervisor**: full access; may switch to Virtual; grants Operator
  permissions (Settings > Operator Permissions).
- **Operator**: no password; permissions default-deny; Product Info
  read-only; Real mode only.
- **Credentials** (SSH / DUT login): stored in the OS keyring
  (macOS Keychain / Windows Credential Manager) - the YAML only keeps
  a `credential_ref`. When the keyring backend is unavailable the app
  falls back to environment variables `MTK_CRED_<REF>` WITH an explicit
  warning; plaintext storage is never used.
- **Supervisor password reset** clears stored credential refs; the
  operator re-enters them (see docs/fct/B3 spec section 7.2).
