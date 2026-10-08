# Getting Started

1. Install: Python 3.9+, `pip install -r requirements.txt`
   (PySide6, pyserial, paramiko, PyYAML, openpyxl, keyring).
2. Launch: `python main.py` (or the packaged executable).
3. Login: **Supervisor** (password required, full access, may switch
   to Virtual mode) or **Operator** (no password, permissions are
   granted by the Supervisor, always Real mode).
4. Load a project: `File > Load Yaml...` (project-format YAML, e.g.
   `projects/96317/A-96317_96317_EVT-(Proto-1)_rev1.1.yaml`).
5. Run: F5 on the Test Work Flow page. Without a YAML the run is
   blocked on purpose.
6. Real vs Virtual: Virtual (Supervisor-only) simulates the whole
   station incl. fault injection; Real drives the physical rack.
