# resources/audio/ - audio assets (BT Tone / A2DP)

WAV files used by the `BT_Tone` step (A2DP stream from the Host PC to
the DUT sink).  Put project music / test tones here; the BT Tone
editor loads them (dual-slider Start/End range + preview + live level
meter).  Pure test tones live in `resources/tones/` (repo-wide);
project music belongs HERE.

You may copy your own files, e.g.:
```bash
cp resources/music/2026-10-30_09-48-46.wav projects/<YourProduct>/assets/resources/audio/
```
