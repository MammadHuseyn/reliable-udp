# Reliable UDP

A small reliable file-transfer protocol built on top of UDP. It is written in python with no external dependencies. 

Contains 3 basic strategies:

| Protocol | Description |
|---|---|
|**Stop-and-Wait (SaW)**| Sends 1 packet, waits for its ACK, retransmits on timeout.|
|**Go-Back-N (GBN)**| Sends packets in `WINDOW`s. Receiver accepts only in-order packets and sends cumulative ACKs. When timeout happens, sends eveything from the oldest unACKed packet.|
|**Selective Repeat (SR)**| Sends packets in `WINDOW`s. Receiver buffers out-of-order packets and ACKs each individually. Sender has timer per packet and resends what is lost.|


Usually, UDP itself can lose, corrupt, duplicate and reorder datagrams. And this project adds checksum, sequence numbers, acknowledgements, retransmission timers, connection handshake on top of UDP.

Packet loss itself is simulated with basic random function.

(TODO: simulate delay, duplication and reordering)


## Requirements
 
- Python 3.8 or newer
- Standard library only (`socket`, `struct`, `random`, `time`, `sys`)


## Project layout
 
```
reliable-udp/
  rudp.py            # shared packet format, checksum, lossy send
  SaW_sender.py      SaW_receiver.py
  GBN_sender.py      GBN_receiver.py
  SR_sender.py       SR_receiver.py
```


## Usage
 
Start the **receiver first**, then the sender. Pick one protocol and use its matching pair of files. The sender and receiver must use the same protocol.
 
```
py <PROTO>_receiver.py <port> <outfile> [loss]
py <PROTO>_sender.py   <file> <host> <port> [loss]
```
 
where `<PROTO>` is `SaW`, `GBN` or `SR`.
 
| Argument | Meaning |
|---|---|
| `port` | UDP port the receiver listens on. |
| `outfile` | Where the receiver writes the received file. |
| `file` | File the sender transmits. |
| `host` | Receiver's IP address (`127.0.0.1` for the same machine). |
| `loss` | Optional. Probability (0.0 to 1.0) that each packet *this program sends* is dropped. Default `0.0`. |
 
On Linux or macOS use `python3` instead of `py`.
 
### Example
 
Terminal 1:
 
```
py SR_receiver.py 9000 received.bin 0.2
```
 
Terminal 2:
 
```
py SR_sender.py somefile.bin 127.0.0.1 9000 0.2
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
 
## Configuration
 
Constants are defined at the top of each file.
 
| Constant | Where | Default | Meaning |
|---|---|---|---|
| `MAX_PAYLOAD` | `rudp.py` | 1024 | Maximum payload bytes per packet. |
| `TIMEOUT` | senders | 0.5 s | Time before an unacked packet is retransmitted. |
| `MAX_RETRIES` | senders | 20 | Retries before giving up (per packet for SaW and SR, consecutive timeouts without progress for GBN). |
| `WINDOW` | GBN / SR sender, SR receiver | 8 | Maximum packets in flight. **The SR sender and receiver must use the same value.** |
| `LINGER` | GBN / SR receivers | 2.0 s | How long the receiver stays alive after the FIN. |
 
Setting `WINDOW = 1` makes GBN and SR behave like stop-and-wait, which is a useful sanity check.
 
## Known limitations
 
- **End-of-transfer uncertainty.** If the last ACKs are lost and the receiver exits before the sender receives one, the sender retries until `MAX_RETRIES` and then reports `gave up on packet N`, even though the file may have arrived completely. Raising `LINGER` reduces this. It is an instance of the two-generals problem, and real protocols such as TCP (TIME_WAIT) only make it unlikely rather than impossible.
- **Fixed timeout.** `TIMEOUT` is a constant and does not adapt to measured round-trip time, and retransmissions don't use exponential backoff.
- **No flow or congestion control.** The window size is fixed.
- **One sender at a time.** The receiver serves a single peer and handles one file per run.
- **Only loss is simulated.** `lossy_sendto` drops packets at random. Delay, duplication and reordering are not simulated yet.
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