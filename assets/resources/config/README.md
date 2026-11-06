# resources/config/ - static configuration files

Static configs pushed to the DUT before tests (wpa_supplicant,
sysctl, daemon configs, ...).  Secrets are NOT kept here in plain
form: prefer the parameterized scripts (env vars / step params).

## wpa_supplicant.conf.template

Reference wpa_supplicant config for an NXP i.MX Linux DUT.  A
`Console_serial` row running your own connect script owns the
credentials now, so this template is for manual / custom use.
Generate a per-SSID conf with:

```sh
wpa_passphrase <SSID> <PASSWORD> > /tmp/wpa.conf
```
