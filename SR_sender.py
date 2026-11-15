import time, sys, socket
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


def main():
    if len(sys.argv)<4:
        sys.exit("usage: py SR_sender.py <file> <host> <port> [loss]")
    if len(sys.argv) == 5:
        loss = float(sys.argv[4])
    else:
        loss = 0.0

    path, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
    addr = (host,port)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    if not handshake(sock, addr, loss):
        sys.exit('could not connect to receiver')

    print('connected')

    with open(path, 'rb') as f:
        data = f.read()

    packets = []
    for i in range(0, len(data), MAX_PAYLOAD):
        packets.append((DATA, data[i:i+MAX_PAYLOAD]))

    packets.append((FIN,b''))
    total = len(packets)

    #per-packet state
    acked = [False] * total #packet n was confirmed?
    sent_time = [0.0] *total #time it was last sent
    retries = [0] * total #number of retransmissions

    def transmit(seq):
        flags, payload = packets[seq]
        lossy_sendto(sock, ppack(flags,seq, 0, payload),addr, loss)
        sent_time[seq] = time.time()

    base = next_seq = 0
    sent = retransmit = 0
    start = time.time()

    sock.settimeout(TIMEOUT)

    while base<total:
        while next_seq<min(total, base+WINDOW):
            transmit(next_seq)
            sent+=1
            next_seq+=1

        #looking for ack

        try:
            raw, _ = sock.recvfrom(2048)
        except (socket.timeout, ConnectionResetError):
            pass
        else:
            parsed = punpack(raw)
            if parsed:
                f, _seq, ack, _payload = parsed
                if f&ACK and not f &SYN and base <= ack < next_seq:
                    acked[ack] = True
                    while base<total and acked[base]:
                        base+=1

        #per-packet timeouts

        now = time.time()
        for i in range(base, next_seq):
            if not acked[i] and now - sent_time[i] > TIMEOUT:
                retries[i]+=1
                if retries[i] > MAX_RETRIES:
                    sys.exit(f'gave up on packet {i}')
                transmit(i)
                retransmit += 1 

    elapsed = time.time() - start
    print(
        f"loss={loss:.0%}, window={WINDOW}, "
        f"sent {sent} packets, "
        f"{retransmit} retransmissions, "
        f"{elapsed:.2f}s"
    )



if __name__ == "__main__":
    main()