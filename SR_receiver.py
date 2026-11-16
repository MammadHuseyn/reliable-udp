import time, sys, socket
from rudp import *

WINDOW = 256
LINGER = 4.0

def main():
    if len(sys.argv)<3:
        sys.exit("usage: py GBN_receiver.py <port> <outfile> [loss]")

    if len(sys.argv)==4:
        loss = float(sys.argv[3])
    else:
        loss = 0.0

    port, outpath = int(sys.argv[1]), sys.argv[2]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    sock.bind(('0.0.0.0', port))
    print(f'listening on UDP {port}')

    rcv_base = 0
    buffer = {} #out of order packets waiting {seq: (flags, payload)}
    peer = None

    with open(outpath, 'wb') as out:
        while True:
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                break
            except ConnectionResetError:
                continue

            parsed = punpack(data)
            if parsed is None:
                continue #corrput data

            flags, seq, _ack, payload = parsed

            if flags&(SYN):
                if peer is None or peer == addr:
                    peer = addr
                    lossy_sendto(sock, ppack(SYN|ACK), addr, loss)
                continue

            if addr != peer:
                continue

            if flags & (DATA|FIN):
                if seq<rcv_base:
                    #already delivered, ack lost, redeliver it
                    lossy_sendto(sock, ppack(ACK,0,seq), addr, loss)

                elif seq < rcv_base  + WINDOW:
                    #inside th window, keep and ack
                    if seq not in buffer:
                        buffer[seq] = (flags,payload)
                    lossy_sendto(sock,ppack(ACK,0,seq), addr, loss)

                    #delovering everytrhing
                    while rcv_base in buffer:
                        f,p = buffer.pop(rcv_base)
                        if f & DATA:
                            out.write(p)
                        else:
                            sock.settimeout(LINGER)
                        rcv_base+=1

                #else if > window+base ignore
    print(f'done: delivered {rcv_base}, packets -> {outpath}')




if __name__ == '__main__':
    main()
