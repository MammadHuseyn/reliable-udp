import socket, time
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rudp import *



TIMEOUT = 0.2 #next, try to replace with adaptive format
MAX_RETRIES = 20 #sender will try to retransmit max this time, else give up
WINDOW = 8

def handshake(sock, addr, loss): #fucntion that performs initial handshake
    syn = ppack(SYN) #seq = 0, ack =0
    for attempt in range(MAX_RETRIES):
        lossy_sendto(sock, syn, addr, loss) #sends packets
        sock.settimeout(TIMEOUT) 
        try:
            data, _ = sock.recvfrom(2048) #wait for udp packet
        except (socket.timeout, ConnectionResetError): #host unreachable error
            continue #no answer yet resend syn
        parsed = punpack(data)
        if parsed and parsed[0] & SYN and parsed[0] & ACK: 
            #parsed -> ensure the packet was successfully deoded
            #parsed[0] & SYN -> checks if packet contains SYN flag
            #parsed[0] & ACK -> checks if oacket contains ACK flag
            #meaning waits for both SYN adn ACK from server (initial response)
            lossy_sendto(sock, ppack(ACK), addr, loss) #then sends plain ACK packet to server
            return True
            #handshake is done   
    return False


#base -> oldest ack seq
#next_seq -> next seq to send
#window -> max number of packets in 1 flight
#timer -> for the packet at base


def main():
    if len(sys.argv)<4:
        sys.exit("usage: py GBN_sender.py <file> <host> <port> [loss]")

    path, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
    if len(sys.argv) == 5:
        loss = float(sys.argv[4])
    else:
        loss = 0.0

    addr = (host,port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    if not handshake(sock, addr, loss):
        sys.exit("could not connect to receiver")

    print("connected")

    with open(path, "rb") as f:
        data = f.read()

    packets = []
    for i in range(0, len(data), MAX_PAYLOAD):
        packets.append((DATA, data[i:i+MAX_PAYLOAD]))

    packets.append((FIN,b''))
    total = len(packets)

    def transmit(seq): #helper fucntion sending packets with seq number
        flags, payload = packets[seq]
        lossy_sendto(sock, ppack(flags, seq, 0, payload), addr, loss)

    base = next_seq =0
    timer = None
    sock.settimeout(0.05) #makes recvfrom waits max 50ms
    timeouts = 0    
    sent = retransmit = 0
    start = time.time()

    while base < total:

        #filling window
        while next_seq < min(base+ WINDOW, total): #while there is room is window and it is less than total(packets left)
            transmit(next_seq)
            sent+=1
            if base == next_seq:
                timer = time.time()

            next_seq += 1

        #cheking and processing ack

        try:
            raw, _ =sock.recvfrom(2048)
        except (socket.timeout, ConnectionResetError):
            pass

        else:
            parsed = punpack(raw)
            if parsed:
                flag ,_seq, ack,_payload = parsed
                if flag & ACK and not flag & SYN and base< ack <= next_seq:
                    base = ack
                    timeouts=0
                    if base< next_seq:
                        timer = time.time()
                    else:
                        timer = None

        #timeout

        if timer is not None and time.time()-timer > TIMEOUT:

            timeouts+=1 
            if timeouts > MAX_RETRIES:
                sys.exit(f'gave up, no progress at packet {base}')

            for i in range(base,next_seq):
                transmit(i)
                retransmit+=1
            timer = time.time()

    elapsed = time.time()  - start

    print(
        f"loss={loss:.0%}, window={WINDOW}, "
        f"sent {sent} packets, "
        f"{retransmit} retransmissions, "
        f"{elapsed:.2f}s"
    )



if __name__ == '__main__':
    main()
