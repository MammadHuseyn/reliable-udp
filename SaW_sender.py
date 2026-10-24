# Stop and wait sender. 
# It does not have a sliding window

import socket
import sys
import time

from rudp import ACK, DATA, FIN, MAX_PAYLOAD, lossy_sendto, ppack, punpack

TIMEOUT = 0.5 #replace with adaptive format
MAX_RETRIES = 20

def send_SaW(sock, addr, flags, seq, payload, loss):
    packet = ppack(flags,seq,0,payload)

    for attemp in range(1, MAX_RETRIES+1):
        lossy_sendto(sock,packet, addr,  loss)
        deadline = time.time()+TIMEOUT 

        while True:
            remainin = deadline - time.time()
            if remainin <= 0:
                break
            sock.settimeout(remainin)
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                break

            parsed = punpack(data)

            if parsed is None:  #if it is a corrupt packet
                continue

            f, _seq, ack, _payload = parsed
            if f & ACK and ack == seq:
                return attemp
            #else duplicate, wait
    
    return None


def main():
    if len(sys.argv)<4:
        sys.exit("usage: py SaW_sender.py <file> <host> <port> [loss]")

    path, host, port = sys.argv[1], sys.argv[2], sys.argv[3]

    if len(sys.argv == 5):
        loss = float(sys.argv[4])
    else:
        loss = 0.0

    addr = (host, port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    #later do connection setup before sending data

    seq = 0
    sent = retransmit = 0
    start = time.time()

    with open(path, "rb") as f:
        while True:
            chunk = f.read(MAX_PAYLOAD)
            if not chunk:
                break
            attemps = send_SaW(sock,addr,DATA, seq, chunk, loss)
            if attemps is None:
                sys.exit(f"gave up on the packet {seq}")
            retransmit += attemps - 1
            sent +=1
            seq +=1
    # Tell the receiver we're done.
    # Known weak spot: if the receiver's final ACK is lost, it has already
    # closed and we'll retry until MAX_RETRIES. TODO: handle FIN properly
    # (e.g. receiver lingers a few seconds after FIN, like TCP's TIME_WAIT).            

    send_SaW(sock,addr, FIN, seq, b"", loss)
    elapsed = time.time() - start
    print(f"sent {sent} packets, {retransmit} retransmissions, {elapsed:.2f}s")

if __name__ == "__main__":
    main()