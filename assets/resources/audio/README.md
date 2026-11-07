# resources/audio/ - audio assets (BT Tone / A2DP)

WAV files used by the `BT_Tone` step (A2DP stream from the Host PC to
the DUT sink).  Put project music / test tones here; the BT Tone
editor loads them (dual-slider Start/End range + preview + live level
meter).  Pure test tones live in `resources/tones/` (repo-wide);
project music belongs HERE.

`2026-10-30_09-48-46.wav` is a bundled sample track (79.6 s, 16 kHz
stereo) so the BT Tone editor has something to browse and preview.
Copy it - or any of your own files - into a project's assets:
```bash
cp assets/resources/audio/2026-10-30_09-48-46.wav \
   projects/<YourProduct>/assets/resources/audio/
```
