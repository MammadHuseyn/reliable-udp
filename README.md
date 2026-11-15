# Reliable UDP

This repository contains three small reliable-file-transfer protocols built on
top of UDP:

1. **Stop-and-Wait (SaW)** - one packet in flight.
2. **Go-Back-N (GBN)** - a window of packets with cumulative acknowledgements.
3. **Selective Repeat (SR)** - a window of packets with individual
   acknowledgements and receiver buffering.

The implementations are educational examples. They demonstrate retransmission,
sequence numbers, acknowledgements, checksums, a simple handshake, and
connection teardown. They are not replacements for TCP, QUIC, or a production
file-transfer protocol.

## Shared packet format

All three implementations use [`rudp.py`](./rudp.py).
Each packet contains a network-byte-order header followed by an optional
payload:

| Field | Size | Description |
| --- | ---: | --- |
| Flags | 1 byte | `DATA`, `ACK`, `SYN`, or `FIN` |
| Sequence number | 4 bytes | Identifies a data or control packet |
| Acknowledgement number | 4 bytes | Identifies the acknowledged packet |
| Payload length | 2 bytes | Payload size |
| Checksum | 2 bytes | Detects damaged packets |

The payload limit is 1024 bytes. The simulated loss function can drop outgoing
packets, but it does not currently simulate delay, duplication, or reordering.

## 1. Stop-and-Wait

### How it works

The sender reads one 1024-byte chunk, sends it, and waits for the matching
acknowledgement before sending the next chunk. If the timeout expires, it
retransmits the same packet. The receiver writes only the next expected
sequence number and acknowledges duplicates without writing them twice.

The sender and receiver perform this flow:

1. Sender sends `SYN`.
2. Receiver responds with `SYN | ACK`.
3. Sender sends the final handshake `ACK`.
4. Data packets are sent and acknowledged one at a time.
5. Sender sends `FIN`; the receiver acknowledges it and briefly accepts
   duplicate `FIN` packets before closing.

### Usage

Start the receiver first:

```powershell
py .\SaW_receiver.py <port> <outfile> [loss]
```

Then start the sender in another terminal:

```powershell
py .\SaW_sender.py <file> <host> <port> [loss]
```

Example:

```powershell
py .\SaW_receiver.py 9000 .\received.bin 0.10
py .\SaW_sender.py .\somefile.bin 127.0.0.1 9000 0.10
```

### Advantages

- Simplest implementation and easiest protocol to inspect.
- Minimal receiver state.
- Straightforward duplicate handling.

### Limitations and known bugs

- Very slow on networks with noticeable round-trip latency because only one
  packet can be outstanding.
- Uses fixed timeouts and a fixed retry limit instead of adaptive retransmission
  timing.
- The sender does not check the return value when sending `FIN`, so it can
  print a successful transfer even if the final acknowledgement was never
  received.
- The sender and receiver do not validate that the loss argument is between
  `0.0` and `1.0`.

## 2. Go-Back-N

### How it works

The sender keeps up to eight packets in flight. The receiver accepts only the
next packet it expects and discards out-of-order packets. Its ACK identifies
the next expected sequence number, so ACKs are cumulative.

When the sender's timer expires, it retransmits every unacknowledged packet in
the current window, even if some of those packets arrived successfully. This
is the defining Go-Back-N behavior.

### Usage

Start the receiver first:

```powershell
py .\GBN_receiver.py <port> <outfile> [loss]
```

Then start the sender:

```powershell
py .\GBN_sender.py <file> <host> <port> [loss]
```

Example:

```powershell
py .\GBN_receiver.py 9001 .\received-gbn.bin 0.10
py .\GBN_sender.py .\somefile.bin 127.0.0.1 9001 0.10
```

### Advantages

- Better throughput than Stop-and-Wait because multiple packets can be in
  flight.
- Less receiver memory and logic than Selective Repeat.
- Cumulative ACKs make the receiver-to-sender protocol simple.

### Limitations and known bugs

- One lost or out-of-order packet causes later packets in the window to be
  discarded and retransmitted.
- The sender uses one fixed timer for the window and retransmits the entire
  window after a timeout.
- The sender reads the complete input file into memory before transferring it.
- The handshake's final `ACK` is not tracked as a formal connection state.
- The implementation does not perform congestion control, flow control, or
  adaptive timeout calculation.

## 3. Selective Repeat

### How it works

The sender also allows up to eight packets in flight, but each packet has its
own acknowledgement, timer, and retry counter. The receiver accepts packets
within its window, stores out-of-order packets in a buffer, and writes them
when all earlier packets have arrived.

When a packet times out, only that packet is retransmitted. After `FIN`, the
receiver waits briefly for duplicate `FIN` packets and then exits, closing the
output file.

### Usage

Start the receiver first:

```powershell
py .\SR_receiver.py <port> <outfile> [loss]
```

Then start the sender:

```powershell
py .\SR_sender.py <file> <host> <port> [loss]
```

Example:

```powershell
py .\SR_receiver.py 9002 .\received-sr.bin 0.20
py .\SR_sender.py .\somefile.bin 127.0.0.1 9002 0.20
```

### Advantages

- Usually more efficient than Go-Back-N when losses are isolated.
- Retransmits only missing packets.
- Receiver buffering allows packets to arrive out of order.

### Limitations and known bugs

- Requires more receiver memory and more per-packet sender state.
- Uses fixed timeouts and a fixed retry limit for every packet.
- The sender reads the complete input file into memory.
- The handshake's final `ACK` is not tracked as a formal connection state.
- Sequence numbers do not wrap and there is no protection against an old
  packet from a previous transfer.
- The receiver's short FIN linger is a simple teardown mechanism, not a full
  connection state machine.

## Comparison

| Implementation | Packets in flight | ACK style | Out-of-order receiver behavior | Retransmission |
| --- | ---: | --- | --- | --- |
| Stop-and-Wait | 1 | Individual | Rejects until expected packet | One packet |
| Go-Back-N | 8 | Cumulative | Discards | Entire active window |
| Selective Repeat | 8 | Individual | Buffers within window | Only timed-out packets |

### Real-world comparison

These implementations mirror classic ARQ protocols, but real-world
transports add substantially more behavior:

- **TCP** uses a byte stream, cumulative acknowledgements, adaptive timers,
  flow control, congestion control, connection states, and modern selective
  acknowledgement extensions.
- **QUIC** runs over UDP but provides reliable streams, encryption,
  authentication, congestion control, connection migration, and loss recovery.
- **Stop-and-Wait, GBN, and SR here** are intentionally small teaching
  implementations. They do not provide encryption, authentication, congestion
  control, flow control, robust peer identity, MTU/path discovery, or durable
  connection recovery.

Use these programs on a trusted local network or for controlled experiments.
Do not use them as a secure or Internet-facing file-transfer service.

## Common troubleshooting

- Start the receiver before the sender.
- Use a different port and output filename for each protocol.
- If an earlier receiver is still running, stop it with `Ctrl+C` before
  restarting it.
- The receiver prints `done` after the `FIN` linger period. The output file is
  closed at that point.
- A loss value such as `0.20` means that approximately 20% of calls to the
  simulated send function may be dropped.
- The sender's reported completion means its local retry loop finished; compare
  the source and output file sizes or hashes to verify the transfer.
