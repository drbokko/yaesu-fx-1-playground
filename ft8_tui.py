#!/usr/bin/env python3
"""FT8 real-time receiver/decoder with htop-style TUI."""

import argparse
import curses
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional

import numpy as np
import pyaudio

from PyFT8.cycle_manager import Cycle_manager
from PyFT8.sigspecs import FT8
from PyFT8.time_utils import global_time_utils


@dataclass
class DecodeLine:
    ts: str
    freq: int
    snr: int
    dt: float
    msg: str


class SharedState:
    def __init__(self, max_msgs: int = 50):
        self.lock = threading.Lock()
        self.decoded: Deque[DecodeLine] = deque(maxlen=max_msgs)
        self.last_spectrum: Optional[np.ndarray] = None
        self.last_update: float = 0.0
        self.n_unfinished: int = 0


def list_devices() -> None:
    pa = pyaudio.PyAudio()
    print("Input devices:")
    for idx in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(idx)
        if info.get("maxInputChannels", 0) > 0:
            print(f"  [{idx:2d}] {info['name']}")
    pa.terminate()


def parse_device_keywords(arg: Optional[str]) -> Optional[List[str]]:
    if not arg:
        return None
    return [s.strip() for s in arg.split(",") if s.strip()]


def make_on_decode(state: SharedState):
    def _on_decode(d: dict) -> None:
        with state.lock:
            state.decoded.appendleft(
                DecodeLine(
                    ts=d.get("cs", ""),
                    freq=int(d.get("f", 0)),
                    snr=int(d.get("snr", 0)),
                    dt=float(d.get("dt", 0.0)),
                    msg=d.get("msg", ""),
                )
            )
    return _on_decode


def make_on_finished(state: SharedState):
    def _on_finished(d: dict) -> None:
        with state.lock:
            state.n_unfinished = int(d.get("n_unfinished", 0))
    return _on_finished


def sample_spectrum(cm: Cycle_manager, state: SharedState) -> None:
    """Periodically sample the latest spectrum slice for display."""
    audio_in = cm.spectrum.audio_in
    while True:
        time.sleep(0.05)
        ptr = audio_in.main_ptr - 1
        if ptr < 0:
            ptr = audio_in.hops_percycle - 1
        row = audio_in.dB_main[ptr].copy()
        with state.lock:
            state.last_spectrum = row
            state.last_update = time.time()


def render_spectrum(
    win,
    spectrum: np.ndarray,
    fmin: int,
    fmax: int,
    df: float,
    width: int,
    palette: str,
) -> str:
    fbin_min = int(fmin / df)
    fbin_max = int(fmax / df)
    fbin_max = min(fbin_max, spectrum.shape[0] - 1)
    fbin_min = max(fbin_min, 0)
    band = spectrum[fbin_min:fbin_max]
    if band.size <= 0:
        return "".ljust(width)

    # Downsample to terminal width
    bins_per_col = max(1, int(np.ceil(band.size / width)))
    cols = []
    for i in range(0, band.size, bins_per_col):
        slice_ = band[i : i + bins_per_col]
        cols.append(float(np.mean(slice_)))
    cols = np.array(cols[:width])

    # Normalize to [0, 1]
    low, high = -120.0, -20.0
    levels = np.clip((cols - low) / (high - low), 0.0, 1.0)
    idxs = (levels * (len(palette) - 1)).astype(int)
    line = "".join(palette[i] for i in idxs)
    return line.ljust(width)


def draw_tui(stdscr, cm: Cycle_manager, state: SharedState, fmin: int, fmax: int) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(100)

    palette = " .:-=+*#%@"

    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()

        # Header
        cycle_time = global_time_utils.cycle_time(FT8.cycle_seconds)
        if h >= 2 and w >= 2:
            try:
                stdscr.addnstr(0, 0, "FT8 Decoder (real-time)".ljust(w), w - 1)
                stdscr.addnstr(1, 0, f"Cycle: {cycle_time:5.2f}s   Freq: {fmin}-{fmax} Hz".ljust(w), w - 1)
            except curses.error:
                pass

        # Spectrum line
        with state.lock:
            spectrum = state.last_spectrum
            n_unfinished = state.n_unfinished
        if spectrum is not None:
            line = render_spectrum(
                stdscr,
                spectrum,
                fmin,
                fmax,
                cm.spectrum.df,
                w,
                palette,
            )
            if h > 3 and w > 1:
                try:
                    stdscr.addnstr(3, 0, line, w - 1)
                    stdscr.addnstr(2, 0, f"Spectrum (dB) — unfinished candidates: {n_unfinished}".ljust(w), w - 1)
                except curses.error:
                    pass
        else:
            if h > 2 and w > 1:
                try:
                    stdscr.addnstr(2, 0, "Spectrum: waiting for data...".ljust(w), w - 1)
                except curses.error:
                    pass

        # Decoded messages
        start_row = 5
        if h > start_row and w > 1:
            try:
                stdscr.addnstr(start_row, 0, "Recent decodes:".ljust(w), w - 1)
            except curses.error:
                pass
        header = "UTC        Freq  SNR  dt   Message"
        if h > start_row + 1 and w > 1:
            try:
                stdscr.addnstr(start_row + 1, 0, header.ljust(w), w - 1)
            except curses.error:
                pass
        with state.lock:
            decoded_list = list(state.decoded)
        max_rows = h - (start_row + 2) - 1
        for i, line in enumerate(decoded_list[:max_rows]):
            row = start_row + 2 + i
            msg = f"{line.ts} {line.freq:5d} {line.snr:4d} {line.dt:4.1f} {line.msg}"
            if h > row and w > 1:
                try:
                    stdscr.addnstr(row, 0, msg, w - 1)
                except curses.error:
                    pass

        if h > 0 and w > 1:
            try:
                stdscr.addnstr(h - 1, 0, "Press q to quit".ljust(w), w - 1)
            except curses.error:
                pass
        stdscr.refresh()

        try:
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                break
        except curses.error:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="FT8 real-time decoder with TUI")
    parser.add_argument("--device", help="Input device keyword(s), comma-separated")
    parser.add_argument("--list-devices", action="store_true", help="List audio input devices and exit")
    parser.add_argument("--fmin", type=int, default=200, help="Minimum frequency (Hz)")
    parser.add_argument("--fmax", type=int, default=3100, help="Maximum frequency (Hz)")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    state = SharedState(max_msgs=80)
    device_keywords = parse_device_keywords(args.device)

    cm = Cycle_manager(
        FT8,
        on_decode=make_on_decode(state),
        on_finished=make_on_finished(state),
        input_device_keywords=device_keywords,
        freq_range=[args.fmin, args.fmax],
        verbose=False,
    )

    sampler = threading.Thread(target=sample_spectrum, args=(cm, state), daemon=True)
    sampler.start()

    try:
        curses.wrapper(draw_tui, cm, state, args.fmin, args.fmax)
    finally:
        if hasattr(cm.spectrum.audio_in, "stream"):
            try:
                cm.spectrum.audio_in.stream.stop_stream()
                cm.spectrum.audio_in.stream.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
