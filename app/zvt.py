"""CCV storage-only ZVT framing (PA00P015, registration and display/input)."""

import socket
import time


ACK = bytes.fromhex("80 00 00")
ALLOWED_COMMANDS = {bytes.fromhex("06 00"), bytes.fromhex("06 E1")}
KEYS = {
    0x31: "1", 0x32: "2", 0x33: "3", 0x34: "4",
    0x0D: "OK", 0x1B: "CANCEL", 0x18: "CANCEL",
    0x55: "+", 0x44: "-", 0x46: "3", 0x6C: "TIMEOUT",
}


def frame(command, payload=b""):
    size = len(payload)
    length = bytes([size]) if size < 255 else b"\xff" + size.to_bytes(2, "little")
    return command + length + payload


def pop_frame(buffer):
    if len(buffer) < 3:
        return None
    header, size = 3, buffer[2]
    if size == 255:
        if len(buffer) < 5:
            return None
        header, size = 5, int.from_bytes(buffer[3:5], "little")
    if size > 4096:
        raise ValueError("ZVT-Antwort ist zu gross.")
    end = header + size
    if len(buffer) < end:
        return None
    result = bytes(buffer[:end])
    del buffer[:end]
    return result


def validate_outbound(data):
    if data != ACK and data[:2] not in ALLOWED_COMMANDS:
        raise ValueError("Unerlaubtes ZVT-Kommando blockiert.")
    buffer = bytearray(data)
    if pop_frame(buffer) != data or buffer:
        raise ValueError("Ungueltiger ZVT-Rahmen.")


def display_frame(lines, duration=5):
    payload = bytearray([0xF0, duration])
    for index, line in enumerate(lines[:8], 1):
        raw = "".join(c if c.isprintable() else " " for c in str(line))[:40].encode("cp437", errors="replace")
        tens, ones = divmod(len(raw), 10)
        payload.extend([0xF0 + index, 0xF0 | tens, 0xF0 | ones])
        payload.extend(raw)
    return frame(b"\x06\xe1", bytes(payload))


def parse_key(data):
    # 31..34 are F1..F4 in 06 E1, not proof of numeric-keypad support.
    if len(data) == 4 and data[:3] == b"\x80\x00\x01":
        return KEYS.get(data[3])
    return None


class Connection:
    def __init__(self, sock, stop_event, observe=lambda direction, data: None):
        self.sock = sock
        self.stop_event = stop_event
        self.observe = observe
        self.buffer = bytearray()

    def send(self, data):
        validate_outbound(data)
        if self.stop_event.is_set():
            raise InterruptedError("ZVT gestoppt.")
        self.sock.sendall(data)
        self.observe("tx", data)

    def receive(self, timeout):
        deadline = time.monotonic() + timeout
        while not self.stop_event.is_set():
            data = pop_frame(self.buffer)
            if data is not None:
                self.observe("rx", data)
                if data[0] == 0x84 and data[1] != 0:
                    raise RuntimeError(f"Terminal lehnt Kommando ab: {data[:2].hex(' ').upper()}")
                if data[:2] == b"\x06\x1e":
                    self.send(ACK)
                    raise RuntimeError(f"Terminal meldet Abbruch: {data.hex(' ').upper()}")
                return data
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Keine vollstaendige Antwort vom CCV-Terminal.")
            self.sock.settimeout(min(0.5, remaining))
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError("CCV-Terminal hat die Verbindung geschlossen.")
            self.buffer.extend(chunk)
        raise InterruptedError("ZVT gestoppt.")

    def register(self, registration):
        self.send(registration)
        if self.receive(8) not in (ACK, b"\x84\x00\x00"):
            raise RuntimeError("ZVT-Registrierung wurde nicht bestaetigt.")
        completion = self.receive(8)
        if completion[:2] != b"\x06\x0f":
            raise RuntimeError("ZVT-Registrierung ohne Abschlussantwort.")
        self.send(ACK)
