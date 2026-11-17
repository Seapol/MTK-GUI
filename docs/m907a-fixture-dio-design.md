# DAQM907A DIO <-> ATE Fixture Control Board: Working Logic Design

Status: design note (no code changed yet).
Scope: the four fixture signals carried by the DAQM907A open-drain port
(Press / In-Position / DUT Presence / E-Stop), the electrical
translation between the two boards, the software state machine and the
safety behaviour of the FCT / ICT sequences.

Anchors in the current tree:

| what | where |
|---|---|
| SCPI templates (`dio_write` / `dio_read`) | `mtkgui/drivers/daq973a.py:42` (keys at `:58`, `:59`) |
| `write_dio(channels, value)` | `mtkgui/drivers/daq973a.py:315` |
| `read_dio(channels)` -> bit pattern | `mtkgui/drivers/daq973a.py:334` |
| fixture op (write vs read-expectation) | `mtkgui/engine/instruments.py:449` |
| fixture read / compare | `mtkgui/engine/instruments.py:477` |
| 4-signal table + direction defaults | `mtkgui/equipment_page.py:329` (`DIO_SIGNALS`) |
| ATE Fixture Control Board config dialog | `mtkgui/equipment_page.py:2149` |
| U2355A DIO write preflight (not reused here) | `mtkgui/engine/runner.py:360` |

---

## 1. Electrical model (the part that decides everything else)

The DAQM907A DIO is an **open-drain** port: each channel is a low-side
switch. It does not source current; it sinks. The fixture control board
supplies the pull-up (station wiring: external pull-up, 42 V / 400 mA
envelope, per the control-board config text).

Consequences that must drive the software:

1. **Wire level is inverted against logical level.**
   `bit = 0` -> switch closed -> current flows -> control-board input
   asserted -> physical action ON (e.g. clamp down).
   `bit = 1` -> switch open -> no current -> action OFF.
   So every output signal needs an `active_low` flag in config; the
   sequence keeps working in logical terms (`H = clamp down`), and only
   the last translation step flips the bit.
2. **A write targets the whole port, not one channel.** The SCPI
   command is `DIG:DATA <value>,(@<channel list>)`; the value is a
   bank bit pattern. Driving one signal must be a
   read-modify-write on the port shadow (see §4), never a raw
   `write 0x0001` that would drop every other channel of the same port
   (indicator lamps, auxiliary relays, another station signal).
3. **Power-on / `*RST` state is not "safe" by definition.** After
   `Init Instruments` the port may come up high-Z (all bits 1 = all
   actions released) or hold the previous pattern. The init sequence
   must therefore *explicitly drive the safe pattern and verify it*
   before any test step runs, instead of assuming.
4. **Read-back is loop state, not actuator state.** Reading a bit
   proves the DAQM latch/line state, not that the cylinder actually
   moved or that the solenoid is energised. Closed-loop proof for the
   Press signal comes from the **In-Position input** (`INPOS = H`
   within a timeout), not from reading the output bit back.

Inputs (In-Position / Presence / E-Stop) arrive as dry contacts or
open-collector from the control board into the same port. They are
**active-low** at the wire: contact closed -> bit 0.

## 2. Signal table (canonical, one row per signal)

| Logical signal | Direction | Logical H means | Logical L means | Safe state | Notes |
|---|---|---|---|---|---|
| `PRESS` | OUT | clamp / cylinder down | released | **L** | drives the clamp solenoid through the control board |
| `INPOS` | IN | cylinder locked (in-position sensor made) | not in position | n/a | the closed-loop proof for `PRESS` |
| `PRESENCE` | IN | **no DUT** (sensor not made, active-low) | **DUT present** | n/a | gate for "may clamp?" |
| `ESTOP` | IN | E-stop pressed / loop open | loop healthy | n/a | gates every write |

Direction defaults in `DIO_SIGNALS` currently read
`press=output, inpos=output, presence=output, estop=input`
(`mtkgui/equipment_page.py:329`). `INPOS` and `PRESENCE` are sensors
coming *from* the fixture, so their default direction must be **input**;
the engine already treats them as read-back (`instruments.py:477`).
Leaving them as "output" only hides the polarity question at
commissioning time and lets an operator configure a write onto a sensor
line. **This is a correction to confirm against the fixture schematic**
(§9, item 1).

## 3. Address model: logical channel -> port + bit

Two namespaces exist today and must not be confused:

* **Logical**: `DIO01..DIO16` (what the config dialog and the sequence
  rows speak).
* **Instrument**: the SCPI channel list inside `(@...)`, e.g. slot-3
  channel numbers of the DAQM907A, and the bank bit pattern passed as
  `DIG:DATA`.

The driver is bank-oriented (`write_dio(channels, value)` /
`read_dio(channels) -> int`), but `_op_fixture` calls
`write_dio(channel, 1 if level == "H" else 0)`
(`mtkgui/engine/instruments.py:472`). Passing the logical name and a
0/1 scalar is not a valid bank write, and it silently loses polarity,
port-sharing and read-back. The design therefore fixes the contract:

```yaml
equipment:
  control_board:
    port_map:
      port1: "3101:3108"        # SCPI channel list, confirmed on site
      port2: "3201:3208"
    signals:
      press:    {channel: DIO01, direction: output, active_low: true,
                 port: port1, settle_ms: 300, timeout_s: 2.0}
      inpos:    {channel: DIO02, direction: input,  active_low: true,
                 port: port1, debounce: 3}
      presence: {channel: DIO03, direction: input,  active_low: true,
                 port: port1, debounce: 3}
      estop:    {channel: DIO04, direction: input,  active_low: true,
                 port: port1, debounce: 3}
```

`bit = (channel_number - 1) % 8` inside its port; the port's channel
list supplies the SCPI address. No hardcoded slot map in code — this
is the same rule the driver docstring already states
(`daq973a.py:18`).

## 4. Software logic

### 4.1 One owner, one shadow

* A single `FixtureDio` object owns the DAQM907A DIO. FCT and ICT
  sequences share it through a lock; two runners must never interleave
  port writes.
* Per port it keeps `shadow: int` — the last pattern it believes is
  latched. `shadow is None` after connect / reconnect / `*RST`, which
  forces a resync read before the first write.

### 4.2 Write path (read-modify-write + verify)

```
set_signal(sig, logical_level):
  1. reject if fixture_type == "Manual"            -> Done, no hardware
  2. reject if sig.direction != output             -> ConfigError
  3. reject if ESTOP reads pressed (unhealthy)     -> WriteRefused
  4. if shadow is None: shadow = read_port(port)
  5. wire_bit  = active_low ? (0 if H else 1) : (1 if H else 0)
  6. do not trip the port if the bit already equals wire_bit
  7. shadow = (shadow & ~mask) | (wire_bit << bit)
  8. write_port(port, shadow)
  9. verify: read_port(port) bit == wire_bit  else -> ReadbackMismatch
 10. log: logical level, channel, port, bit, wire level, verify result
```

Step 6 is what keeps a 4-signal fixture from generating a bus write on
every redundant `Fixture Clamp Down` row; step 9 is what keeps a
half-broken cable from looking like a pass.

### 4.3 Read path (decoded state vector)

```
read_state() -> {press, inpos, presence, estop}   # logical levels
```

One port read decodes all four signals (mask + active_low), with
`debounce` consecutive samples required for an input to change state.
This single read feeds the step verdict, the status line and the
E-stop watchdog — one place, one truth.

### 4.4 Expectation semantics (keep the engine contract)

`_read_fixture` (`instruments.py:477`) already distinguishes:

* `expect` -> mismatch = **Fail** (product / fixture problem),
* `unexpected` -> present = **Fail**,
* no expectation -> plain write, **Done**.

Communication problems stay **Error** (never Fail): timeout, no reply,
parse failure, DAQ `SYST:ERR?` non-zero. The rule "Fail = the bench said
no, Error = we could not ask the bench" must hold everywhere.

## 5. Fixture state machine

```
                 +---------------- IDLE (safe: PRESS=L) ----------------+
                 |                                                        |
  Init/SafeState |                                                        | Release
                 v                                                        |
        check_ready() -- PRESENCE=L? ESTOP=L? --> no --> refuse, LOG "cannot clamp"
                 |
                 v
             CLAMPING:  PRESS=H  -> wait settle_ms -> poll INPOS
                 |                                   |
                 |  INPOS=H within timeout_s         |  timeout / ESTOP trips
                 v                                   v
             CLAMPED (run allowed)               CLAMP_FAIL -> PRESS=L, Fail
                 |
                 |  Power On DUT (only when CLAMPED)
                 v
             TESTING  --(ESTOP pressed, step fail, operator abort)--> ABORT
                 |
                 v
             UNCLAMPING: PSU off -> PRESS=L -> verify INPOS=L (within timeout)
                 |
                 v
                IDLE
```

Hard rules encoded by this machine:

1. **No clamp without a ready bench**: `PRESENCE=L` (DUT present) and
   `ESTOP=L` (healthy) are preconditions of `PRESS=H`. A clamp on an
   empty socket is a hardware-damaging action, so it is a refusal
   (ERROR), not a FAIL.
2. **No DUT power without a proven clamp**: `Power On DUT` requires
   `CLAMPED` (PRESS verified + INPOS=H). This is the interlock the
   sequence ordering already implies
   (`projects/FRDM-IMX93/.../fct_linux.yaml:20`,
   `Init -> fixture -> power`), now made explicit rather than
   order-by-convention.
3. **E-stop wins over everything**: an E-stop edge at any time ->
   PSU output OFF, `PRESS=L`, all outputs to safe pattern, sequence
   aborts, remaining rows reported as not executed. The E-stop input is
   also a *hardware* chain on the control board — the DIO read is the
   software confirmation, never the safety mechanism itself (§9, item 4).
4. **Every exit path releases the clamp**: step fail, operator abort,
   application close, instrument reconnect, unhandled exception. The
   clamp is not allowed to survive the process (§7).

## 6. Sequence timing / where the waits live

| transition | wait | source |
|---|---|---|
| PRESS=H -> read INPOS | `settle_ms` (default 300 ms, configurable per signal) | `control_board.signals.press` |
| INPOS poll | until `timeout_s` (default 2.0 s), poll every 50 ms | same |
| PRESS=L -> read INPOS | `settle_ms` + `timeout_s` | same |
| input debounce | N consecutive equal samples (default 3) | `signals.*.debounce` |

The engine must not carry magic numbers: `Delay` rows are for DUT
behaviour (boot time, RF settle), fixture settle/debounce belong to the
control-board config, exactly as the M49a note puts the DIO mapping into
that config (`.trae/documents/m49a-equipment-page-rework.md:87`).

## 7. Lifecycle & failure handling

| event | required action |
|---|---|
| app start / `Init Instruments` | explicit safe pattern, verify, `shadow` valid |
| DAQ reconnect | `shadow = None`; next access resyncs by reading the port first |
| `*RST` sent by `Reset Instruments` | same as reconnect: invalidate shadow, re-apply safe pattern |
| test abort / stop button | PSU off -> PRESS=L -> verify |
| app close (normal) | same shutdown order, logged; never `kill -9` the process |
| write refused (unhealthy E-stop / not ready) | ERROR with the exact reason in the row detail, no retry storm |
| readback mismatch | FAIL on the row if an expectation existed, otherwise ERROR — a fixture wiring fault is not a DUT verdict |

Retry policy: at most 2 retries on transport errors, never on
readback mismatch or refusal (repeating a wrong action does not make it
right).

## 8. Log wording (operator-facing, one line per action)

```
fixture PRESS: drive DIO01 (port1 bit0) H -> wire L -> readback OK (3 ms)
fixture state: PRESENT=yes INPOS=locked ESTOP=healthy CLAMP=down
fixture PRESS: cannot clamp - DUT presence = no (DIO03 H)   [ERROR]
fixture INPOS: expect High within 2.0 s - read Low at 2.0 s  [FAIL]
fixture ESTOP: pressed - PSU OFF, clamp released, sequence aborted [FAIL]
```

Rules: name the logical signal, the channel, the port/bit, the logical
and wire level, and the elapsed time; never print a bare "DIO write
done". Distinguish ERROR (could not act / refused) from FAIL (bench said
no).

## 9. Open points that need bench confirmation

1. **Direction defaults** — `INPOS` / `PRESENCE` should be `input`
   (sensor lines), contradicting `equipment_page.py:329`. Confirm from
   the fixture schematic before changing the default.
2. **SCPI channel form / slot** — `3101:3108` above is a placeholder
   shape. Confirm the real DAQM907A channel numbering of the installed
   slot from the manual; today the code passes `DIO01`, which is not a
   legal channel address. No new SCPI verbs beyond `DIG:DATA` /
   `DIG:DATA?` may be invented (`.traerules` §5); if direction
   configuration needs a command, it must be verified on site first.
3. **Drive stage** — is the solenoid driven directly by the open-drain
   channel (within the 42 V / 400 mA envelope) or through a relay /
   MOSFET on the control board? This decides whether read-back of the
   output bit means anything at all, and whether a flyback path must be
   specified.
4. **E-stop rating** — software reading the loop is confirmation only.
   The physical E-stop must cut the clamp/power in hardware; if today it
   only reaches a DAQM input, that is a safety finding, not a software
   feature.
5. **`presence` polarity naming** — the config field is "DUT presence"
   but its electrical sense is active-low; keep one convention
   (logical level) in YAML and one (`active_low`) for the wire, never
   mix "High = absent" into the sequence rows.

## 10. Acceptance tests

Unit (mocked transport, no hardware):

1. RMW leaves neighbouring bits of the same port untouched.
2. `active_low` inversion is applied exactly once, on the wire only.
3. Same-level rewrite produces no bus write (idempotency), and the
   first apply still verifies.
4. Duplicate channel rejected in the config dialog; direction
   `input` refuses an output op with a ConfigError.
5. Missing `port_map` -> ConfigError naming the exact key.
6. Readback mismatch -> ERROR (no expectation) / FAIL (expectation).
7. `Manual` fixture -> Done, zero driver calls.
8. E-stop edge during TESTING -> shutdown order asserted: PSU off,
   PRESS=L, verify, abort.

Bench (real rack):

9. Short/open each input at the control-board connector and watch all
   four decoded states.
10. Clamp with the socket empty -> must be refused; clamp with a DUT ->
    INPOS=H within the timeout.
11. Pull the E-stop during a run -> PSU off and clamp released within
    the documented time, logged.
12. Kill-free exit: close the app with the clamp down -> clamp
    released before the process exits.
