import socket, time
from rudp import *


#base -> oldest ack seq
#next_seq -> next seq to send
#window -> max number of packets in 1 flight
#timer -> for the packet at base

def send_all(sock, addr, chunks, window=8, timeout=0.5, loss=0.0):
    base = next_seq =0
    total = len(chunks)
    timer = None
    sock.settimeout(0.05)

    while base < total:

        #filling window
        while next_seq < min(base+window, total):
            pkt = ppack(DATA, seq = next_seq, payload = chunks[next_seq])
            lossy_sendto(sock, pkt, addr, loss)

            if base == next_seq: #first packet in flight, starts the timer
                timer = time.time()
            next_seq += 1

        #cheking and processing ack

        try:
            raw, _ =sock.recvfrom(2048)
            p=punpack(raw)
            if p and p[0] & ACK and p[2]> base:
                base = p[2] #cACK slides the window
                if base<next_seq:
                    timer = time.time()
                else:
                    timer = None
        except socket.timeout:
            pass

        #timeout

        if timer and time.time()-timer>timeout:
            for i in range(base,next_seq):
                lossy_sendto(sock, ppack(DATA, seq=i, payload = chunks[i]),addr,loss)
            timer = time.time()
    