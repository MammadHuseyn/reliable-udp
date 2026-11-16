import argparse #to write user-friendly command-line interfaces
#trying to learn it instead of sys
import signal
import socket
from collections import deque
import time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('listen_port', type=int)
    parser.add_argument('dest_host')
    parser.add_argument('dest_port', type=int)
    parser.add_argument('--rate', type = float, default=200, help = 'bottleneck speed, packets/second')
    parser.add_argument('--queue', type = int, default=20, help='queue capacity in packets')
    parser.add_argument('--delay',type=float,default=0.02, help='one-way delay, seconds')
    parser.add_argument('--loss', type=float, default=0.0, help='random loss')
    parser.add_argument('--log', help-'wirte time,queue_len,droppped')

    args = parser.parse_args()

    def stop(*_):
        raise KeyboardInterrupt
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, stop)

    server = (args.des_host, args.dest_port) #receivers addr
    client = None #sender's addr
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #IPv4 UDP socket
    sock.bind(('0.0.0.0', args.listen_port))

    # relay
    service_time = 1.0 / args.rate
    link_free = 0.0  #when bottleneck link becomes available
    iqueue = deque()
    pending = [] #packets waiting for delivery
    #delivery_time seq_num,packet,destination
    counter = 0 #seq number for pending

    forwarded = dropped = max_q = 0

    log = open(args.log,'w') if args.log else None
    if log:
        log.write('time,queue_len,dropped\n')
    t0 = time.time()
    print(f'relay :{args.listen_port} -> {server},  rate={args.rate} pkt/s,  queue={args.queue},  one-way delay{args.delay*1000} ms')
    #delay * 2 = RTT
    #rate * RTT = exact number of packets to be in flight
    print(f'bandwidth-delay produc ~ {args.rate * 2 * args.delay} packets '
          f'(window above ~ {args.rate * 2 * args.delay + args.queue} will overflow the queue)')

    