# FT8 Real-Time Decoder (TUI)

A real-time FT8 receiver/decoder with an **htop-style terminal UI**. It uses the `PyFT8` decoder core and renders a live spectrum line plus decoded messages.

> **Note:** FT8 decoding is CPU-heavy. A modern laptop should manage real-time decoding for a narrow band (e.g., 200–3100 Hz). Wider ranges can increase load.

## Features
- Real-time audio capture (PyAudio)
- FT8 sync + LDPC decoding (PyFT8)
- Htop-like TUI with live spectrum line
- Recent decodes table

## Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## List audio devices
```bash
python ft8_tui.py --list-devices
```

## Run
```bash
python ft8_tui.py --device "USB Audio" --fmin 200 --fmax 3100
```

- `--device` accepts **comma-separated keywords**; the first matching input device is used.
- `--fmin`/`--fmax` define the spectrum slice to search (Hz).

## Controls
- Press **q** to quit.

## Notes
- Use a narrow IF/audio band for best performance.
- Adjust `--fmin/--fmax` to your receiver output.
- If you get no decodes, confirm your audio device is selected and that FT8 signals are present.

## Troubleshooting
- **PyAudio install fails**: On macOS, you may need `brew install portaudio`.
- **No devices**: Ensure the input device is connected and accessible to the system.

## License
MIT
