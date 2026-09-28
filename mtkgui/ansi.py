# -*- coding: utf-8 -*-
"""ANSI escape-sequence decoder for the serial console.

A byte stream from the serial port is turned into
``(text, attributes)`` segments. The SGR state (colors, bold, ...) is
kept between calls, and an escape sequence - or a multi-byte UTF-8
character - split across two serial reads is buffered and completed on
the next call.

Supported SGR codes:

* ``0`` reset; ``1`` bold; ``2`` dim; ``3`` italic; ``4`` underline;
  ``7`` reverse; ``22/23/24/27`` undo
* ``30-37`` / ``40-47`` standard foreground / background
* ``90-97`` / ``100-107`` bright foreground / background
* ``38;5;n`` / ``48;5;n`` 256 colors
* ``38;2;r;g;b`` / ``48;2;r;g;b`` true color
* ``39`` / ``49`` default foreground / background

Other CSI and OSC sequences (cursor movement, title strings, ...) are
silently stripped.
"""

ESC = 0x1B

# Classic xterm / VGA 16-color palette.
ANSI_16 = [
    "#000000", "#cd0000", "#00cd00", "#cdcd00",
    "#0000ee", "#cd00cd", "#00cdcd", "#e5e5e5",
    "#7f7f7f", "#ff0000", "#00ff00", "#ffff00",
    "#5c5cff", "#ff00ff", "#00ffff", "#ffffff",
]


def color_256(index):
    """Return the hex color for an ANSI 256-color index."""
    if index < 16:
        return ANSI_16[index]
    if index < 232:
        index -= 16
        levels = [0, 95, 135, 175, 215, 255]
        r = levels[(index // 36) % 6]
        g = levels[(index // 6) % 6]
        b = levels[index % 6]
        return f"#{r:02x}{g:02x}{b:02x}"
    value = 8 + (index - 232) * 10
    return f"#{value:02x}{value:02x}{value:02x}"


def _default_attrs():
    return {
        "fg": None,
        "bg": None,
        "bold": False,
        "dim": False,
        "italic": False,
        "underline": False,
        "reverse": False,
    }


class AnsiDecoder:
    """Stateful stream decoder. Use :meth:`feed` with each received chunk."""

    def __init__(self):
        self._pending = b""
        self.attrs = _default_attrs()

    def reset(self):
        self.attrs = _default_attrs()
        self._pending = b""

    # ---------------------------------------------------------------- feed
    def feed(self, data):
        """Return a list of ``(text, attrs)`` segments for one chunk."""
        data = self._pending + data
        self._pending = b""
        segments = []
        pos = 0

        while pos < len(data):
            esc = data.find(ESC, pos)
            if esc == -1:
                text, tail = self._decode_run(data[pos:])
                if text:
                    segments.append((text, self._snapshot()))
                if tail:
                    self._pending = tail
                break

            if esc > pos:
                text, _tail = self._decode_run(data[pos:esc])
                if text:
                    segments.append((text, self._snapshot()))

            consumed = self._parse_escape(data, esc)
            if consumed is None:  # incomplete sequence, wait for more bytes
                self._pending = data[esc:]
                break
            pos = consumed
        return segments

    # ------------------------------------------------------------- decoding
    @staticmethod
    def _decode_run(chunk):
        """Decode a run with no ESC inside.

        Returns ``(text, unterminated_multibyte_tail)``.
        """
        try:
            return chunk.decode("utf-8"), b""
        except UnicodeDecodeError:
            cut = len(chunk)
            if cut and chunk[-1] >= 0x80:
                cont = 0
                while (cont < cut
                       and 0x80 <= chunk[cut - 1 - cont] < 0xC0):
                    cont += 1
                lead_pos = cut - 1 - cont
                if cont < cut and chunk[lead_pos] >= 0xC0:
                    lead = chunk[lead_pos]
                    if lead >= 0xF0:
                        expected = 4
                    elif lead >= 0xE0:
                        expected = 3
                    else:
                        expected = 2
                    if cont + 1 < expected:
                        good = chunk[:lead_pos].decode(
                            "utf-8", errors="replace")
                        return good, chunk[lead_pos:]
            return chunk.decode("utf-8", errors="replace"), b""

    def _snapshot(self):
        return dict(self.attrs)

    # --------------------------------------------------------- escape parse
    def _parse_escape(self, data, i):
        """Return the index right after the escape, or None if incomplete."""
        if i + 1 >= len(data):
            return None
        nxt = data[i + 1]

        if nxt == 0x5B:  # CSI
            j = i + 2
            while j < len(data) and 0x30 <= data[j] <= 0x3F:
                j += 1
            while j < len(data) and 0x20 <= data[j] <= 0x2F:
                j += 1
            if j >= len(data):
                return None
            if 0x40 <= data[j] <= 0x7E:
                if data[j] == 0x6D:  # 'm' = SGR
                    params = data[i + 2:j].decode("ascii", errors="ignore")
                    self._apply_sgr(params)
                return j + 1
            return None

        if nxt == 0x5D:  # OSC, ends with BEL or ESC \\
            end = None
            bel = data.find(0x07, i + 2)
            if bel != -1:
                end = bel + 1
            k = data.find(ESC, i + 2)
            while k != -1 and (k + 1 >= len(data)
                               or data[k + 1] != 0x5C):
                k = data.find(ESC, k + 1)
            if k != -1:
                if k + 1 >= len(data):
                    return None
                cand = k + 2
                end = cand if end is None else min(end, cand)
            return end

        # Other escapes: optional intermediate bytes then one final byte.
        j = i + 1
        while j < len(data) and 0x20 <= data[j] <= 0x2F:
            j += 1
        if j >= len(data):
            return None
        return j + 1

    # ----------------------------------------------------------------- SGR
    def _apply_sgr(self, params):
        if not params:
            self.attrs = _default_attrs()
            return
        try:
            nums = [int(p) if p else 0 for p in params.split(";")]
        except ValueError:
            return
        i = 0
        while i < len(nums):
            code = nums[i]
            if code == 0:
                self.attrs = _default_attrs()
            elif code == 1:
                self.attrs["bold"] = True
            elif code == 2:
                self.attrs["dim"] = True
            elif code == 3:
                self.attrs["italic"] = True
            elif code == 4:
                self.attrs["underline"] = True
            elif code == 7:
                self.attrs["reverse"] = True
            elif code == 22:
                self.attrs["bold"] = False
                self.attrs["dim"] = False
            elif code == 23:
                self.attrs["italic"] = False
            elif code == 24:
                self.attrs["underline"] = False
            elif code == 27:
                self.attrs["reverse"] = False
            elif 30 <= code <= 37:
                self.attrs["fg"] = ANSI_16[code - 30]
            elif 40 <= code <= 47:
                self.attrs["bg"] = ANSI_16[code - 40]
            elif 90 <= code <= 97:
                self.attrs["fg"] = ANSI_16[code - 90 + 8]
            elif 100 <= code <= 107:
                self.attrs["bg"] = ANSI_16[code - 100 + 8]
            elif code in (38, 48):
                target = "fg" if code == 38 else "bg"
                if i + 1 < len(nums):
                    mode = nums[i + 1]
                    if mode == 5 and i + 2 < len(nums):
                        self.attrs[target] = color_256(nums[i + 2])
                        i += 2
                    elif mode == 2 and i + 4 < len(nums):
                        r, g, b = nums[i + 2:i + 5]
                        self.attrs[target] = (
                            f"#{r & 255:02x}{g & 255:02x}{b & 255:02x}")
                        i += 4
            elif code == 39:
                self.attrs["fg"] = None
            elif code == 49:
                self.attrs["bg"] = None
            i += 1
