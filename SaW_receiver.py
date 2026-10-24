import socket
import sys

from rudp import ACK, DATA, FIN, lossy_sendto, ppack, punpack

def main():
    if len(sys.argv) <3:
        sys.exit("usage: py SaW_receiver.py <port> <outfile> [loss]")

    port, outpath = int(sys.argv[1]), sys.argv[2]
    if len(sys.argv) == 4:
        loss = float(sys.argv[3])
    else:
        loss = 0.0

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))
    print(f"listening on UDP {port}")

    expected = 0 #next seq number we are waiting for

    with open(outpath, "wb") as out:
        while True:
            data, addr = sock.recvfrom(2048)
            parsed = punpack(data)

            if parsed is None:
                continue    #corrupt

            flags, seq, _ack, payload = parsed

            if flags & DATA:
                if seq == expected:
                    out.write(payload)
                    expected +=1
                # Whether new or a duplicate of something we already have,
                # ACK it. A duplicate usually means OUR ACK got lost.

                if seq < expected:
                    lossy_sendto(sock, ppack(ACK, 0, seq), addr, loss)

            elif flags & FIN:
                lossy_sendto(sock, ppack(ACK,0,seq),addr, loss)

                sock.settimeout(0.2)

                while(True):
                    try:
                        data, addr = sock.recvfrom(2048)
                    except socket.timeout:
                        break
                    parsed=punpack(data)
                    if parsed and parsed[0] & FIN:
                        lossy_sendto(sock, ppack(ACK,0,parsed[1]), addr, loss)
                break

    print(f"done: received {expected} packets -> {outpath}")

if __name__ == "__main__":
    main()