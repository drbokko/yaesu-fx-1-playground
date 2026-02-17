#!/usr/bin/env python3
"""Basic FX-1 CAT serial status reader.

Opens the CAT control port and prints incoming bytes. Optionally sends a
poll/status command. Includes basic parsing for FA (frequency) responses.
"""

import argparse
import binascii
import sys
import time
from typing import Optional

import serial


DEFAULT_PORTS = [
    "/dev/tty.usbmodem00000000000011",
    "/dev/tty.usbserial-01C9ECBC0",
]

MODE_CODES = {
    "LSB": "1",
    "USB": "2",
    "CW-U": "3",
    "FM": "4",
    "AM": "5",
    "RTTY-L": "6",
    "CW-L": "7",
    "DATA-L": "8",
    "RTTY-U": "9",
    "DATA-FM": "A",
    "FM-N": "B",
    "DATA-U": "C",
    "AM-N": "D",
    "DATA-FM-N": "F",
    "C4FM-DN": "H",
    "C4FM-VW": "I",
}

VFO_CODES = {
    "MAIN": "0",
    "SUB": "1",
}


def parse_hex_bytes(hex_str: str) -> bytes:
    cleaned = hex_str.replace(" ", "").replace("0x", "")
    if len(cleaned) % 2 != 0:
        raise ValueError("Hex string length must be even")
    return binascii.unhexlify(cleaned)


def open_serial(port: str, baud: int) -> serial.Serial:
    return serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.2,
    )


def send_poll(ser: serial.Serial, payload: bytes) -> None:
    ser.write(payload)
    ser.flush()


def parse_fa(buf: bytearray) -> Optional[int]:
    """Parse FAxxxxxxxxx; frequency response from buffer.

    Returns frequency in Hz if found, otherwise None.
    """
    try:
        data = buf.decode("ascii", errors="ignore")
    except Exception:
        return None
    start = data.find("FA")
    if start == -1:
        return None
    end = data.find(";", start)
    if end == -1:
        return None
    digits = data[start + 2 : end]
    if not digits.isdigit():
        return None
    return int(digits)


def read_loop(
    ser: serial.Serial,
    raw: bool,
    parse_fa_enabled: bool,
    poll_every: Optional[float],
    poll_payload: Optional[bytes],
) -> None:
    buf = bytearray()
    last_poll = 0.0
    while True:
        if poll_every and poll_payload and (time.time() - last_poll) >= poll_every:
            send_poll(ser, poll_payload)
            last_poll = time.time()
        data = ser.read(256)
        if data:
            buf.extend(data)
            if raw:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            else:
                hex_str = data.hex(" ")
                print(hex_str)
            if parse_fa_enabled:
                freq = parse_fa(buf)
                if freq is not None:
                    print(f"FA: {freq} Hz")
                    buf.clear()
                    return
            else:
                return


def main() -> None:
    parser = argparse.ArgumentParser(description="FX-1 CAT serial status reader")
    parser.add_argument(
        "--port",
        default=None,
        help="Serial port path (default: first available from common FX-1 control ports)",
    )
    parser.add_argument("--baud", type=int, default=38400, help="Baud rate (default: 38400)")
    parser.add_argument(
        "--poll",
        help="Hex bytes to send once at startup (e.g. 'FA;') or '0x' hex bytes",
    )
    parser.add_argument(
        "--poll-every",
        type=float,
        help="Send --poll or --poll-hex at this interval (seconds)",
    )
    parser.add_argument(
        "--poll-hex",
        help="Hex bytes to send once at startup, e.g. 'FA03FD'",
    )
    parser.add_argument("--raw", action="store_true", help="Print raw bytes instead of hex")
    parser.add_argument("--parse-fa", action="store_true", help="Parse FA (frequency) responses")
    parser.add_argument(
        "--set-freq",
        type=int,
        help="Set frequency in Hz (sends FAxxxxxxxxx;)",
    )
    parser.add_argument(
        "--set-mode",
        help="Set mode by name (e.g., USB, LSB, DATA-U) or raw code (e.g., 2).",
    )
    parser.add_argument(
        "--vfo",
        default="MAIN",
        help="Target VFO for set-mode: MAIN or SUB (default: MAIN)",
    )
    args = parser.parse_args()
    port = args.port
    if port is None:
        for candidate in DEFAULT_PORTS:
            try:
                ser = open_serial(candidate, args.baud)
                port = candidate
                break
            except Exception:
                continue
        if port is None:
            raise SystemExit("No default FX-1 port found; pass --port explicitly")
    else:
        ser = open_serial(port, args.baud)

    print(f"Connected to {port} @ {args.baud} 8N1")

    poll_payload = None
    if args.poll:
        try:
            poll_payload = args.poll.encode("ascii")
            send_poll(ser, poll_payload)
            print(f"Sent ASCII poll: {args.poll}")
        except Exception as exc:
            print(f"Failed to send poll: {exc}")

    if args.poll_hex:
        try:
            poll_payload = parse_hex_bytes(args.poll_hex)
            send_poll(ser, poll_payload)
            print(f"Sent HEX poll: {args.poll_hex}")
        except Exception as exc:
            print(f"Failed to send hex poll: {exc}")

    if args.set_freq is not None:
        cmd = f"FA{args.set_freq:09d};".encode("ascii")
        send_poll(ser, cmd)
        print(f"Set frequency: {args.set_freq} Hz")

    if args.set_mode is not None:
        mode_in = str(args.set_mode).upper()
        mode_code = MODE_CODES.get(mode_in, mode_in)
        vfo_code = VFO_CODES.get(str(args.vfo).upper())
        if vfo_code is None:
            raise SystemExit("Invalid --vfo. Use MAIN or SUB.")
        if mode_code not in set(MODE_CODES.values()) and mode_code not in MODE_CODES:
            # allow raw single-char code
            if len(mode_code) != 1:
                raise SystemExit("Invalid mode. Use known mode name or single code.")
        cmd = f"MD{vfo_code}{mode_code};".encode("ascii")
        send_poll(ser, cmd)
        print(f"Set mode: VFO={args.vfo} code={mode_code}")

    try:
        read_loop(ser, args.raw, args.parse_fa, args.poll_every, poll_payload)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
