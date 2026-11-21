import socket, time, sys
from rudp import *


from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LINGER = 1.0 #to retransmit after FIN


def main():
    if len(sys.argv)<3:
        sys.exit("usage: py GBN_receiver.py <port> <outfile> [loss]")

    if len(sys.argv)==4:
        loss = float(sys.argv[3])
    else:
        loss = 0.0

    port, outpath = int(sys.argv[1]), sys.argv[2]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #creating UDP socket and listen on port xxxx
    sock.bind(('0.0.0.0', port))
    print(f'listening on UDP {port}')

    expected = 0 #the seq of the next in-order packet 
    peer=None #ip,port of the sender is talkig
    #peer locks the receiver onto the first sender that handshakes, so other hosts cant corrupt the packets

    with open (outpath, 'wb') as out:
        while True:
            try:
                data, addr = sock.recvfrom(2048)
                #waiting for 1datagram
            except socket.timeout:
                break #lingered long enough after fin
            except  ConnectionResetError:
                continue #windows icmp quirk | happens when icmp "port unreachable" error comes

            parsed = punpack(data)
            if parsed is None:
                continue #corrupt data

            flags, seq, _ack, payload = parsed

            if flags & SYN: #cheking is it is a handshake request
                if peer is None or addr == peer: #no peer, setting connection
                    peer = addr
                    lossy_sendto(sock, ppack(SYN | ACK), addr, loss)
                continue

            if addr!=peer: #is it from the same sender?
                continue

            if flags&(DATA|FIN):
                if seq == expected: #is it in order packet
                    if flags & DATA:
                        out.write(payload)
                    else:
                        sock.settimeout(LINGER)
                    expected+=1
                lossy_sendto(sock, ppack(ACK,0,expected),addr, loss)

    print(f'done: received {expected-1} packets -> {outpath}')


if __name__ == '__main__':
    main()