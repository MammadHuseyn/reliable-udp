# Reliable UDP

A small reliable file-transfer protocol built on top of UDP, written in Python with no external dependencies.

It contains three classic reliability strategies, plus a congestion-controlled sender built on Selective Repeat:

| Protocol | Description |
|---|---|
| **Stop-and-Wait (SaW)** | Sends one packet, waits for its ACK, retransmits on timeout. |
| **Go-Back-N (GBN)** | Sends packets in a `WINDOW`. The receiver accepts only in-order packets and sends cumulative ACKs. On timeout, the sender resends everything from the oldest unACKed packet. |
| **Selective Repeat (SR)** | Sends packets in a `WINDOW`. The receiver buffers out-of-order packets and ACKs each one individually. The sender has a timer per packet and resends only what was lost. |
| **Congestion control (CC)** | Selective Repeat with an adaptive timeout (RTT estimation) and a congestion window `cwnd` (slow start and AIMD) and fast loss detection, tested against a simulated bottleneck router (`relay.py`). |

UDP itself can lose, corrupt, duplicate and reorder datagrams. This project adds a checksum, sequence numbers, acknowledgements, retransmission timers and a connection handshake on top of it.

Packet loss is simulated with a basic random function. The congestion-control experiments additionally use a relay that simulates a rate-limited link with a queue and a delay.

(TODO: simulate delay, duplication and reordering in `lossy_sendto`.)


## Requirements

- Python 3.8 or newer
- Standard library only (`socket`, `struct`, `random`, `time`, `sys`, `argparse`, ...)


## Project layout

```
reliable-udp/
  rudp.py                  # shared packet format, checksum, lossy send
  README.md
  .gitignore
  stop_and_wait/
    SaW_sender.py          SaW_receiver.py
  go_back_n/
    GBN_sender.py          GBN_receiver.py
  selective_repeat/
    SR_sender.py           SR_receiver.py
  congestion/
    cc_sender.py           # SR sender with adaptive timeout, cwnd and fast loss detection
    relay.py               # simulated bottleneck router
```

Every sender and receiver imports `rudp.py` from the repository root. Each script adds the root to Python's search path itself, so it works no matter which folder you run it from:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rudp import ...
```

The commands below assume you are in the repository root.


## Usage

Start the **receiver first**, then the sender. Pick one protocol and use its matching pair of files. The sender and receiver must use the same protocol.

```
py <folder>/<PROTO>_receiver.py <port> <outfile> [loss]
py <folder>/<PROTO>_sender.py   <file> <host> <port> [loss]
```

| Protocol | Folder | `<PROTO>` |
|---|---|---|
| Stop-and-Wait | `stop_and_wait` | `SaW` |
| Go-Back-N | `go_back_n` | `GBN` |
| Selective Repeat | `selective_repeat` | `SR` |

| Argument | Meaning |
|---|---|
| `port` | UDP port the receiver listens on. |
| `outfile` | Where the receiver writes the received file. |
| `file` | File the sender transmits. |
| `host` | Receiver's IP address (`127.0.0.1` for the same machine). |
| `loss` | Optional. Probability (0.0 to 1.0) that each packet *this program sends* is dropped. Default `0.0`. |

On Linux or macOS use `python3` instead of `py`, and `/` in paths.

File paths such as `somefile.bin` and `received.bin` are relative to the folder you run the command from, not to the script.

### Example

Terminal 1:

```
py selective_repeat/SR_receiver.py 9000 received.bin 0.2
```

Terminal 2:

```
py selective_repeat/SR_sender.py somefile.bin 127.0.0.1 9000 0.2
```

The sender prints a summary when it finishes:

```
connected
loss=20%, window=8, sent 41 packets, 13 retransmissions, 3.06s
```

### Verify the transfer

The received file should be identical to the original:

```
fc /b somefile.bin received.bin      # Windows
cmp somefile.bin received.bin        # Linux / macOS (no output = identical)
```

### About the `loss` argument

Loss is applied **independently by each side** to the packets it sends. The sender's loss drops data packets (and SYNs), and the receiver's loss drops ACKs. Passing `0.2` to both therefore loses about 20% of data packets *and* 20% of ACKs. The two values don't have to match.


## Packet format

Every packet is a 13-byte header followed by up to 1024 bytes of payload. The header is packed in network byte order (`struct` format `!BIIHH`).

| Field | Size | Meaning |
|---|---|---|
| `flags` | 1 byte | Bit flags (see below). |
| `seq` | 4 bytes | Sequence number of this packet. |
| `ack` | 4 bytes | Acknowledgement number. |
| `payload_len` | 2 bytes | Number of payload bytes. |
| `checksum` | 2 bytes | 16-bit Internet checksum over header and payload. |

**Flags** (each is one bit, and can be combined with `|`):

| Flag | Value | Meaning |
|---|---|---|
| `DATA` | `0x01` | Packet carries file data. |
| `ACK` | `0x02` | Acknowledges a received packet. |
| `SYN` | `0x04` | Connection request. |
| `FIN` | `0x08` | End of transfer. |

A packet is tested with `flags & FLAG` and combined with `FLAG1 | FLAG2`. For example, the handshake reply is `SYN | ACK`.

**Sequence numbers count packets, not bytes.** The first data packet is 0, the next is 1, and so on. The FIN packet takes the next number after the last data packet. A 4-byte field never wraps in practice for this use.

**Checksum.** The sender computes it with the checksum field set to zero. The receiver recomputes it the same way and silently discards any packet that doesn't match, as well as any packet whose length doesn't match `payload_len`. A dropped corrupt packet is recovered by the normal retransmission mechanism. The checksum function was taken from an existing ping implementation: <https://github.com/MammadHuseyn/ping-traceroute_cmmds/blob/main/ping.py>.


## How it works

### Connection setup (all protocols)

A three-way handshake, with the sender retrying the SYN if no reply arrives:

```
Sender                    Receiver
  | ---- SYN ------------> |
  | <--- SYN|ACK --------- |   receiver remembers the sender's address
  | ---- ACK ------------> |
  | ---- DATA / DATA ...   |
```

The receiver locks onto the first sender that completes a SYN and ignores packets from any other address. If the final ACK is lost, nothing breaks, because the receiver doesn't wait for it.

### Stop-and-Wait

- Sender sends packet `seq` and waits up to `TIMEOUT` for an ACK with `ack == seq`.
- If it times out, it resends the same packet, up to `MAX_RETRIES` times, then gives up.
- Receiver writes in-order packets and ACKs every data packet it sees, including duplicates (a duplicate usually means its own ACK was lost).

### Go-Back-N

- The sender keeps `base` (oldest unacked packet) and `next_seq` (next packet to send), and may have up to `WINDOW` packets in flight (`next_seq < base + WINDOW`).
- ACKs are **cumulative**: `ack = N` means "I have every packet below N and expect N next".
- There is **one timer**, for `base`. On timeout the sender resends every packet from `base` to `next_seq - 1`.
- The receiver accepts only the next expected packet and discards everything else. It always replies with `ack = expected`, so out-of-order and duplicate packets cause the last good ACK to be repeated.

### Selective Repeat

- The sender keeps per-packet state: an `acked` flag, the time of the last transmission, and a retry count.
- ACKs are **individual**: `ack = N` means "I received packet N".
- Each packet has its own timeout, and only expired, unacked packets are resent. When the oldest packet is acked, `base` slides forward past every consecutive acked packet.
- The receiver keeps `rcv_base` (next packet to write to the file) and a `buffer` dictionary for packets that arrived early:
  - `seq < rcv_base`: already delivered, so re-ACK it (the earlier ACK was probably lost).
  - `rcv_base <= seq < rcv_base + WINDOW`: buffer it, ACK it, then write out every contiguous packet.
  - `seq >= rcv_base + WINDOW`: beyond the window, so ignore it.

### Ending a transfer (GBN and SR)

The FIN is simply the last packet in the sequence and goes through the same reliable window as data, so it is retransmitted if lost. After the FIN has been delivered, the receiver **lingers** for `LINGER` seconds and re-ACKs any retransmitted packets, so that a lost final ACK doesn't leave the sender retrying forever.


## Congestion control

The fixed-window protocols above send at a speed the programmer chose. On a shared network, that speed has to be found at run time: too slow wastes capacity, too fast overflows router queues, and every dropped packet becomes a retransmission that makes the overload worse. `congestion/cc_sender.py` is the Selective Repeat sender with the pieces that fix this: an **adaptive timeout**, a **congestion window** and **fast loss detection**.

### The simulated network: `relay.py`

Random loss does not depend on how fast you send, so congestion control would have nothing to react to. `relay.py` is a fake router placed between sender and receiver:

```
sender  -->  relay  -->  receiver      forward path: rate limit + queue + delay
sender  <--  relay  <--  receiver      reverse path: delay only
```

On the forward path the link sends `--rate` packets per second. At most `--queue` packets can wait; any packet arriving when the queue is full is dropped (drop-tail). Every delivered packet is then delayed by `--delay` seconds. So losses now happen *because* the sender goes too fast.

```
py congestion/relay.py <listen_port> <dest_host> <dest_port>
                       [--rate 200] [--queue 20] [--delay 0.02] [--loss 0.0] [--log queue.csv]
```

| Option | Meaning | Default |
|---|---|---|
| `--rate` | Bottleneck speed, packets per second | 200 |
| `--queue` | Queue capacity, packets | 20 |
| `--delay` | One-way delay, seconds | 0.02 |
| `--loss` | Extra random loss (both directions) | 0.0 |
| `--log` | Write queue length over time to a CSV file | off |

Stop it with Ctrl+C, which prints how many packets were forwarded and dropped. On start it prints the **bandwidth-delay product** (rate x round-trip time), which is the number of packets that fit in the pipe. With the defaults that is 8 packets; the queue adds 20 more, so a window above about 28 overflows it.

### Running an experiment

Use three terminals, in this order:

```
py congestion/relay.py 9000 127.0.0.1 9001
py selective_repeat/SR_receiver.py 9001 out.bin
py congestion/cc_sender.py bigfile.bin 127.0.0.1 9000 --log cc.csv
```

- The sender sends to the **relay's** port (9000), not the receiver's.
- Use a big file (1 MB or more), otherwise the transfer ends before the window behavior is visible.
- **Keep the sender's `loss` at 0.** Random loss is misread as congestion and keeps `cwnd` tiny. Let the relay's queue create the losses.
- The SR receiver's `WINDOW` must be at least `MAX_CWND` (set it to 256).
- `--window N` makes `cc_sender.py` use a fixed window of N instead of `cwnd`, which is useful for comparison.
- `--timeout-only` turns fast loss detection off, so losses are found only by timeout. Useful for comparing the two.
- `--log` writes `time, event, cwnd, ssthresh, pipe, srtt, rto` to a CSV file for plotting.

### Adaptive timeout (RTT estimation)

A fixed `TIMEOUT` is wrong on almost every network. `cc_sender.py` measures the round-trip time of each packet and derives the timeout from it (RFC 6298):

```
SRTT   = 7/8 * SRTT   + 1/8 * sample
RTTVAR = 3/4 * RTTVAR + 1/4 * |SRTT - sample|
RTO    = SRTT + 4 * RTTVAR
```

- **Karn's rule:** an ACK for a retransmitted packet is not used as a sample, because it is unclear which transmission it answers.
- **Exponential backoff:** after a timeout, `RTO` doubles (up to `MAX_RTO`) until a new valid sample arrives.

### Congestion window

`cwnd` is the number of packets the sender may have in the network at once. It starts at 1 and changes continuously:

| Phase | Rule | Effect |
|---|---|---|
| **Slow start** (`cwnd < ssthresh`) | `cwnd += 1` per ACK | Doubles every RTT |
| **Congestion avoidance** (`cwnd >= ssthresh`) | `cwnd += 1 / cwnd` per ACK | Grows by about 1 packet per RTT |
| **Mild loss** (fast detection, or a timeout while later packets still arrive) | `ssthresh = cwnd / 2`, `cwnd = ssthresh` | Halve the window and continue in congestion avoidance |
| **Severe loss** (timeout, nothing arriving) | `ssthresh = cwnd / 2`, `cwnd = 1` | Halve the remembered limit, restart with slow start |

Slow increase with fast decrease is called **AIMD** (additive increase, multiplicative decrease). Plotting `cwnd` over time gives the typical sawtooth.

Implementation details that matter:

- **`pipe`** counts packets believed to be in the network (sent, not acked, not marked lost). The sender sends only while `pipe < cwnd`, which also means each returning ACK releases exactly one new packet (ACK clocking).
- **`lost`** holds packets declared lost (by fast detection or by timeout). They are retransmitted before new data, and count against `cwnd`, so recovery after a cut also starts slowly instead of flooding the queue again.
- **`recovery_end`:** a burst of drops from one queue overflow is one loss event, so `cwnd` is cut once. Packets lost that were sent before the last cut do not cause another cut.

### Fast loss detection

Waiting for a timeout is slow: a lost packet is noticed only after a full RTO, and by then the sender has stopped. Instead, `cc_sender.py` uses the **packet threshold** rule from QUIC (RFC 9002):

> A packet is lost if a packet sent at least `PACKET_THRESHOLD` (3) transmissions after it has already been acknowledged.

One or two later packets arriving first could just be reordering; three is treated as a loss. This finds a loss about one RTT after it happens, while the network is still delivering packets.

- **Transmission ids, not sequence numbers.** Every send, including every retransmission, gets a new increasing id (`tx_of[seq]`). The rule compares ids, so a fresh retransmission of an old sequence number is not immediately declared lost again just because later sequence numbers were ACKed long ago.
- **`largest_acked_tx`** is the highest transmission id known to be delivered. Only ACKs of packets that were never retransmitted update it (same reasoning as Karn's rule: for a retransmitted packet it is unclear which transmission the ACK answers).
- **No RTO backoff** on a fast loss, because the network is still working.

Timeouts are still needed, for losses the threshold cannot see, for example the last packets of a transfer (there are not three later packets to be ACKed). A timeout is then classified:

| Situation | Meaning | Reaction |
|---|---|---|
| New loss event, later packets **were** ACKed | Isolated loss the threshold missed | Halve (`cwnd = ssthresh`), counted as a fast cut |
| New loss event, **nothing** later ACKed (`stalled`) | The path delivered nothing for a whole RTO | `cwnd = 1`, counted as a timeout cut |
| Same event, a **retransmission** timed out and nothing arrives | Even the halved window is not working | `cwnd = 1` (ssthresh is not halved again) |
| Same event, otherwise | Another drop from a loss already handled | Only logged |

The sender's summary reports `timeout cuts` and `fast cuts` separately. Running the same experiment with and without `--timeout-only` shows most cuts moving from the first to the second, and a shorter transfer time.

### What you should see

With the default relay settings and a large file:

1. `cwnd` doubles every RTT at the start (slow start).
2. It overshoots the capacity of the path, because a loss is noticed only about one RTT after the queue overflows, and the first loss event happens.
3. After that it oscillates around the path capacity (pipe + queue, about 28 packets here): mostly fast cuts that halve `cwnd`, followed by slow linear growth, which gives the AIMD sawtooth. `srtt` rises as the queue fills and falls after each cut.
4. Compared with a fixed window, a window that is too large causes many queue drops and retransmissions, a window that is too small leaves the link underused, and `cwnd` finds a good level on its own.
5. With `--timeout-only`, every loss costs a full RTO and sends `cwnd` back to 1, so the transfer is slower and the plot shows repeated slow starts instead of a sawtooth.

### Constants (`cc_sender.py`)

| Constant | Default | Meaning |
|---|---|---|
| `INITIAL_RTO` | 0.5 s | Timeout used until the first RTT sample exists. |
| `MIN_RTO` | 0.05 s | Lower limit for the timeout. |
| `MAX_RTO` | 2.0 s | Upper limit for the timeout (and for backoff). |
| `MAX_RETRIES` | 12 | Retransmissions of one packet before giving up. |
| `ALPHA`, `BETA`, `K` | 1/8, 1/4, 4 | RTT estimator weights (RFC 6298). |
| `INITIAL_CWND` | 1 | Starting congestion window. |
| `INITIAL_SSTHRESH` | 1000 | Starting slow-start threshold (effectively unlimited). |
| `MAX_CWND` | 200 | Hard cap, must stay below the receiver's `WINDOW`. |
| `PACKET_THRESHOLD` | 3 | Later transmissions that must be ACKed before a packet is declared lost (fast loss detection). |

`INITIAL_RTO` and `MIN_RTO` deliberately differ from RFC 6298 (1 s each) because the experiments run on localhost, where the real round trip is a few milliseconds.


## Configuration (fixed-window protocols)

Constants are defined at the top of each file.

| Constant | Where | Default | Meaning |
|---|---|---|---|
| `MAX_PAYLOAD` | `rudp.py` | 1024 | Maximum payload bytes per packet. |
| `TIMEOUT` | senders | 0.5 s | Time before an unacked packet is retransmitted. |
| `MAX_RETRIES` | senders | 20 | Retries before giving up (per packet for SaW and SR, consecutive timeouts without progress for GBN). |
| `WINDOW` | GBN / SR sender, SR receiver | 8 | Maximum packets in flight. **The SR receiver's `WINDOW` must be at least the sender's.** |
| `LINGER` | GBN / SR receivers | 2.0 s | How long the receiver stays alive after the FIN. |

Setting `WINDOW = 1` makes GBN and SR behave like stop-and-wait, which is a useful sanity check.

When the SR receiver is used with `cc_sender.py`, set `LINGER` to at least `2 x MAX_RTO` (4 s), so a backed-off retransmission still finds the receiver alive.


## Known limitations

- **End-of-transfer uncertainty.** If the last ACKs are lost and the receiver exits before the sender receives one, the sender retries until `MAX_RETRIES` and then reports `gave up on packet N`, even though the file may have arrived completely. Raising `LINGER` reduces this. It is an instance of the two-generals problem, and real protocols such as TCP (TIME_WAIT) only make it unlikely rather than impossible.
- **Fixed timeout in SaW, GBN and SR.** `TIMEOUT` is a constant there and does not adapt to measured round-trip time. Only `cc_sender.py` estimates RTT and backs off exponentially.
- **Fast loss detection only uses the packet threshold.** QUIC also declares a packet lost when it is older than about 9/8 of the RTT while newer packets were ACKed (time threshold), and replaces the RTO with a probe timeout (PTO). Neither is implemented, so losses at the end of a transfer still wait for a full RTO.
- **ACKs of retransmitted packets do not help fast detection.** Because sequence numbers are reused for retransmissions, those ACKs are ambiguous and are ignored for `largest_acked_tx`. Under heavy loss, detection falls back to timeouts. QUIC avoids this by never reusing packet numbers.
- **Random loss is treated as congestion.** Like classic TCP Reno, `cc_sender.py` cannot tell the two apart.
- **No flow control.** The receiver does not advertise its free buffer space. The sender simply keeps `cwnd` below a fixed cap.
- **One sender and one flow at a time.** The receiver serves a single peer and handles one file per run. Fairness between competing senders has not been tested.
- **Simplified network model.** `relay.py` has a single drop-tail queue in the forward direction, counts packets rather than bytes, and the sender-side `lossy_sendto` only simulates loss (no delay, duplication or reordering).
- **No encryption or authentication.** The checksum detects accidental corruption only.


## Benchmark

Setup: 100,000-byte file (99 data packets plus the FIN), 10 trials per setting, 4 transfers running in parallel, localhost, window = 8, `TIMEOUT = 0.1 s`, `LINGER = 0.5 s`. Values are mean ± standard deviation. Loss is applied to both data packets and ACKs.

| Loss | Protocol | OK | Time (s) | Retransmissions | Packets sent |
|---|---|---|---|---|---|
| 10% | SaW | 10/10 | 2.26 ± 0.63 | 20.1 ± 5.8 | 98.0 |
| 10% | GBN | 10/10 | 1.40 ± 0.34 | 84.1 ± 19.2 | 99.0 |
| 10% | SR | 10/10 | 1.30 ± 0.23 | 23.3 ± 5.8 | 99.0 |
| 20% | SaW | 10/10 | 6.74 ± 1.38 | 60.7 ± 12.6 | 98.0 |
| 20% | GBN | 10/10 | 3.02 ± 0.55 | 187.6 ± 33.9 | 99.0 |
| 20% | SR | 10/10 | 2.43 ± 0.41 | 53.9 ± 9.7 | 99.0 |
| 30% | SaW | 10/10 | 12.16 ± 1.84 | 110.1 ± 16.0 | 98.0 |
| 30% | GBN | 10/10 | 5.56 ± 1.07 | 341.8 ± 64.0 | 99.0 |
| 30% | SR | 10/10 | 3.63 ± 0.80 | 97.5 ± 17.6 | 99.0 |

("Packets sent" counts first transmissions only. SaW's count excludes the FIN, which is why it shows one less.)