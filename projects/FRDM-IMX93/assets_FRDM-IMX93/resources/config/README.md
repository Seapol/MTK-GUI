# resources/config/ - static configuration files

Static configs pushed to the DUT before tests (wpa_supplicant,
sysctl, daemon configs, ...).  Secrets are NOT kept here in plain
form: prefer the parameterized scripts (env vars / step params).

## wpa_supplicant.conf.template

Reference wpa_supplicant config for an NXP i.MX Linux DUT.  The
`Wi-Fi: Connect DUT to AP` step generates its own conf from the
Wi-Fi page (SSID/password), so this template is for manual /
custom use.  Generate a per-SSID conf with:

```sh
wpa_passphrase <SSID> <PASSWORD> > /tmp/wpa.conf
```
