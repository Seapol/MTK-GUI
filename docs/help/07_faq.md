# FAQ / Troubleshooting

- **"no nets found"** when parsing: the file has no recognizable
  netlist content - check you loaded the NET (not the SPF) file.
- **"no 'Address' field in the project YAML"**: the instrument entry
  has no Address - configure it on the Equipment page (Virtual mode
  Tools batch does not need one).
- **"power rail CSV log missing"** (rare, Virtual): re-run; if it
  repeats, check the rails capture window vs the sequence delays.
- **Connect failed** on a console: port busy / wrong baud; Virtual
  mode needs no hardware - the fake DUT port appears without a device.
- **"keyring unavailable"** warning: credentials fall back to
  environment variables `MTK_CRED_<REF>` - set them or fix the OS
  keyring; plaintext storage is never used.
- **Run blocked: no YAML loaded**: load a project first
  (File > Load Yaml).
- **Overall IGNORE**: only a Stop with NO failed item shows Ignore;
  any FAIL (even after Stop) reports FAIL.
