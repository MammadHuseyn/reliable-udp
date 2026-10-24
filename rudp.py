# RELIABLE UDP #

import struct

DATA, ACK, SYN, FIN = 1,2,4,8 #Flag bits
#DATA 0x01 - indicates the packet contains use payload data
#ACK  0x02 - confirms receipt of packets
#SYN  0x04 - initiates connection handshake
#FIN  0x08 - terminates connection

#Header -> flags (1), seq (4), ack (4), payload_len (2), checksum(2) -> total 13 bytes
HEADER = struct.Struct("!BIIHH")
MAX_PAYLOAD = 1024

#taken from https://github.com/MammadHuseyn/ping-traceroute_cmmds/blob/main/ping.py
def checksum(data: bytes) -> int:

    if len(data) %2: #adding padding, cause checksum processes data in 2-byte groups
        data+=  b"\x00"
    total = 0
    for i in range(0, len(data), 2): #reading two bytes at time
        #byte packing
        total += (data[i] << 8) + data[i+1] #2bytes become one 16 bit number
        # 0x12 << 8 = 0x1200
        # 0x1200 + 0x34 = 0x1234
    total = (total >> 16) + (total & 0xFFFF)
    #if sum exceeds 16 bits, oveflow is wrapped and added back to lower 16bits
    total += total >> 16
    #second possible carry
    return ~total & 0xFFFF
    #~ flips every bit.
    #0xFFFF keeps only the lowest 16 bits


def ppack(flags: int, seq=0, ack=0, payload=b""):

    head = HEADER.pack(flags,seq, ack, len(payload), 0)
    csum = checksum(head + payload)
    head = HEADER.pack(flags, seq, ack, len(payload), csum)

    return head + payload

def punpack(packet:bytes):
    if len(packet)<HEADER.size:
        return None

    payload = packet[HEADER.size:]
    flags, seq, ack, length, csum = HEADER.unpack(packet[:HEADER.size:])

    if len(payload)!= length:
        return None

    header = HEADER.pack(flags,seq,ack,length,0)
    check_csum = checksum(header + payload)

    if check_csum != csum:
        return None

    return flags, seq, ack, payload