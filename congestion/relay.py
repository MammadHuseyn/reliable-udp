# the forwards path acts like a router. The link(cable or whatever) sends 'rate' packets per second
# arriving packets waits in queue and if it is full, then it drops the new one
# delivered ones are delayed with 'delay'
# default vars:
# RTT 40 ms, link -> 200 packets/second
# bandwidth-delay product 200*0.04=8packets. -> how much data fits in pipe at once
# relay prints start, windw size where overflow (28)


import argparse #to write user-friendly command-line interfaces
#trying to learn it instead of sys
import signal
import socket
from collections import deque
import time
import heapq
import random




def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('listen_port', type=int)
    parser.add_argument('dest_host')
    parser.add_argument('dest_port', type=int)
    parser.add_argument('--rate', type = float, default=200, help = 'bottleneck speed, packets/second')
    parser.add_argument('--queue', type = int, default=20, help='queue capacity in packets')
    parser.add_argument('--delay',type=float,default=0.02, help='one-way delay, seconds')
    parser.add_argument('--loss', type=float, default=0.0, help='random loss')
    parser.add_argument('--log', help='wirte time,queue_len,droppped')

    args = parser.parse_args()

    def stop(*_):
        raise KeyboardInterrupt
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, stop)

    server = (args.dest_host, args.dest_port) #receivers addr
    client = None #sender's addr
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) #IPv4 UDP socket
    sock.bind(('0.0.0.0', args.listen_port))

    # relay
    service_time = 1.0 / args.rate #time the link takes to process one packet 1/200 = 0.005 = 5ms
    link_free = 0.0  #when bottleneck link becomes available
    iqueue = deque()
    pending = [] #packets waiting for delivery
    #delivery_time seq_num,packet,destination
    counter = 0 #seq number for heap

    forwarded = dropped = max_q = 0

    log = open(args.log,'w') if args.log else None
    if log:
        log.write('time,queue_len,dropped\n')
    t0 = time.time()
    print(f'relay :{args.listen_port} -> {server},  rate={args.rate} pkt/s,  queue={args.queue},  one-way delay {args.delay*1000} ms')
    #delay * 2 = RTT
    #rate * RTT = exact number of packets to be in flight
    print(f'bandwidth-delay produc ~{args.rate * 2 * args.delay} packets '
          f'(window above ~{args.rate * 2 * args.delay + args.queue} will overflow the queue)')


    #packet delivery
    try:
        while True:
            now = time.time()

            #delivering packets in pending
            while pending and pending[0][0] <= now:
                _,_, packet, dest = heapq.heappop(pending)
                #time counter packet client
                try:
                    sock.sendto(packet, dest)
                except OSError: #ignores socket errors
                    pass

            #waiting for next packet
            if not pending: #if no delayed packets exits
                timeout = 0.5
            else: #when next packet should be delivered
                timeout = max(0.0002, pending[0][0] - now)
            sock.settimeout(timeout)
            try:
                packet, addr = sock.recvfrom(4096)
            except socket.timeout, ConnectionResetError:
                continue

            now = time.time()

            #if loss is less than random number be drop the packet
            if args.loss and random.random() < args.loss:
                continue

            #if packet is from our server
            if addr == server:
                if client is not None:#only if we know the client
                    counter+=1
                    heapq.heappush(pending, (now + args.delay, counter, packet, client))
                continue


            #the first packet from sende
            if client is None:
                client = addr
            elif  addr != client:
                continue

             # sender -> receiver: through the bottleneck queue
            while iqueue and iqueue[0] <= now:
                iqueue.popleft() #removes packets whose transmission has already completed

            is_full = len(iqueue) >= args.queue
            if is_full: #counts packet as dropped, no room in queue
                dropped+=1
            else: #when queue has space
                start = max(link_free, now) #if link is free now, else wait
                link_free = start + service_time
                iqueue.append(link_free)
                counter+=1
                heapq.heappush(pending,(link_free+args.delay, counter, packet, server))
                forwarded +=1
                max_q = max(max_q, len(iqueue))

            if log:
                log.write(f'{now-t0}, {len(iqueue)}, {int(is_full)}\n')

    except KeyboardInterrupt:
        pass
    finally:
        if log:
            log.close()
        total = forwarded +dropped
        print(f'\nforward path: {forwarded} forwarded, {dropped} droppe by the queue'
              f' ({dropped / total:.1%} of {total}), max queue length {max_q}'
              if total else '\nno traffic')


if __name__ == '__main__':
    main()
        

            