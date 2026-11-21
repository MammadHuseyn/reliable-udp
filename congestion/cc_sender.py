import argparse, socket, sys, time

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from rudp import *

#RTO - retransmission timeout
#RTT - round trip time
#SRTT - smoothed round trip time
#RTTVAR - RTT variation, measure of jitter. how much RTT fluctues form SRTT


#RFC 6298 formulas
#Initial
#SRTT = RTT
#RTTVAR = RTT / 2
#RTO = SRTT + max(Clock_G, K * RTTVAR)

#RTTVAR = (1 - beta) * RTTVAR + beta * abs(SRTT - RTT)
#SRTT = (1 - alpha) * SRTT + alpha * RTT
#RTO = SRTT + max(Clock_G, K * RTTVAR)

INITIAL_RTO = 0.5 #local so no need to make it 6
MIN_RTO = 0.05
MAX_RTO = 2.0
MAX_RETRIES = 12 

ALPHA = 1 / 8 #smoothing weight given to new RTT samples when updating SRTT
BETA = 1 / 4 # smoothing weight given to new delay deviations when updating RTTVAR
K = 4 # RTO = SRTT + K * RTTVAR
CLOCK_G = 0.01 #Clock Granularity | smallest time tick your system clock can reliably measure


#congestion control
INITIAL_CWND = 1.0
INITIAL_SSTHRESH = 1000.0 #slow start threshold
MIN_SSTHRESH = 2.0
MAX_CWND = 200

#fast loss detection quic
PACKET_THRESHOLD = 3




class RTTEstimator:
    #Based on RFC 6298

    def __init__(self):
        self.srtt = None
        self.rttvar = None
        self.rto = INITIAL_RTO

    def sample(self, r):
        #r seconds
        if self.srtt is None: #first measurement
            self.srtt = r
            self.rttvar = r/2
        else:
            self.rttvar = (1-BETA) * self.rttvar + BETA * abs(self.srtt-r)
            self.srtt = (1 - ALPHA) * self.srtt + ALPHA * r

        rto = self.srtt + max(CLOCK_G, K * self.rttvar)
        self.rto = min(max(rto, MIN_RTO), MAX_RTO)

    def backoff(self):
        #when timeout happens, wait 2 times longer next time
        self.rto = min(self.rto*2, MAX_RTO)


def handshake(sock : socket.socket, addr, loss, est : RTTEstimator):
    syn = ppack(SYN)
    for attemp in range(MAX_RETRIES):
        t_sent = time.time()
        lossy_sendto(sock, syn, addr, loss)
        sock.settimeout(est.rto)
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            est.backoff()
            continue
        except ConnectionResetError:
            time.sleep(0.2)
            continue
        parsed = punpack(data)
        if parsed and parsed[0] & SYN and parsed[0] & ACK:
            if attemp == 0: #The Retransmission Ambiguity Problem | Karn's Algorithm
                est.sample(time.time()-t_sent)
            lossy_sendto(sock,ppack(ACK), addr, loss)
            return True
    return False

def main():
    parsed = argparse.ArgumentParser()
    parsed.add_argument('file')
    parsed.add_argument('host')
    parsed.add_argument('port', type=int)
    parsed.add_argument("loss_pos", nargs="?", type=float, default=None, metavar="loss")
    parsed.add_argument('--loss', type=float,  default = None)
    parsed.add_argument('--window', type = int, default = None)
    parsed.add_argument("--timeout-only", action="store_true", help="disable fast loss detection (step 4 behaviour)")
    parsed.add_argument('--log', help = 'write RTT / ROT samples to this cv file')
    args = parsed.parse_args()

    addr = (args.host, args.port)
    loss = args.loss_pos if args.loss_pos is not None else (args.loss or 0.0)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    est = RTTEstimator()
    fixed = args.window is not None
    fast = not args.timeout_only

    if not handshake(sock, addr, loss, est):
        sys.exit('could not connect to the receiver')
    print('connected')

    with open(args.file, 'rb') as f:
        data = f.read()

    packets = []
    for i in range(0,len(data), MAX_PAYLOAD):
        packets.append((DATA, data[i:i+MAX_PAYLOAD]))
    packets.append((FIN, b''))
    total = len(packets)

    acked = [False] * total
    sent_time = [0.0] * total
    retries = [0] * total
    lost = set() #packets we consider lost and still have to retransmit


    
    #every transmission gets a incrreasing id
    #fat loss deetction comapres this ids, not seq numbers
    #fresh retransmissin is not declared lost because later data was acked

    tx_of = [0]*total
    tx_counter = 0
    largest_acked_tx = -1


    #congestion state
    cwnd = float(args.window) if fixed else INITIAL_CWND
    ssthresh = INITIAL_SSTHRESH
    cap = args.window if fixed else MAX_CWND
    pipe = 0    #packets we believe that are in the network, sent, not acked, not marked lost
    recovery_end = 0 #losses of packets below this belong to an event


    if args.log:
        log = open(args.log, 'w')
    else: 
        log = None
    
    start = time.time()

    def record(event):
        if log:
            log.write(f"{time.time() - start:.4f},{event},{cwnd:.3f},{ssthresh:.2f},"
                      f"{pipe},{est.srtt or 0:.5f},{est.rto:.5f}\n")

    if log:
        log.write('time,event,cwnd,ssthresh,pipe,srtt,rto\n')

    def transmit(seq):
        nonlocal tx_counter
        flags, payload = packets[seq]
        lossy_sendto(sock, ppack(flags, seq, 0, payload), addr, loss)
        sent_time[seq] = time.time()
        tx_of[seq] = tx_counter
        tx_counter += 1

    base = next_seq = 0
    sent = retransmit =timeouts = fast_cuts = 0
    max_cwnd_seen = cwnd
    record("start")

    while base<total:
        #filling window (while pipe has rooms)
        allowed=max(1,int(min(cwnd,cap)))
        while pipe<allowed:
            if lost:
                s=min(lost)
                lost.discard(s)
                retries[s]+=1
                if retries[s]>MAX_RETRIES:
                    sys.exit(f'gave up on packet {s}')
                transmit(s)
                retransmit+=1
            elif next_seq<total and next_seq<base+cap:
                transmit(next_seq)
                sent+=1
                next_seq+=1
            else:
                break
            pipe +=1



        #read acks
        wait = 0.01
        for _ in range(256):
            sock.settimeout(wait)
            try:
                raw, _ = sock.recvfrom(2048)
            except (socket.timeout , BlockingIOError, ConnectionResetError):
                break
            wait = 0.0
            parsed = punpack(raw)
            if not parsed:
                continue
            f, _seq, ack, _payload = parsed
            if f & ACK and not f & SYN and base<=ack<next_seq and not acked[ack]:
                acked[ack]= True

                if ack in lost:
                    lost.discard(ack)
                else:
                    pipe -=1

                if retries[ack] == 0: # Karn's rulel
                    sample = time.time() - sent_time[ack]
                    est.sample(sample)
                    largest_acked_tx = max(largest_acked_tx, tx_of[ack])

                if not fixed:
                    if cwnd<ssthresh:
                        cwnd+=1 #slow start, doubles every rtt
                    else:
                        cwnd+=1.0/cwnd #congestion avoidance +1per rtt
                    cwnd = min(cwnd, MAX_CWND)
                    max_cwnd_seen = max(max_cwnd_seen, cwnd)
                
                while base<total and acked[base]:
                    base+=1
                record("ack")


        #fast loss detection

        if fast and largest_acked_tx >= 0:
            fast_lost = [s for s in range(base, next_seq)
                         if not acked[s] and s not in lost 
                         and largest_acked_tx - tx_of[s] >= PACKET_THRESHOLD]
            if fast_lost:
                for s in fast_lost:
                    lost.add(s)
                    pipe-=1
                if not fixed and max(fast_lost) >= recovery_end:
                    ssthresh = max(cwnd/2, MIN_SSTHRESH)
                    cwnd =  ssthresh
                    recovery_end = next_seq
                    fast_cuts += 1
                    record('fast_cut')
                else:
                    record('fast_lost')




        #per packet timeouts
        now = time.time()

        #expired = []
        newly_lost = [s for s in range(base, next_seq)
                      if not acked[s] and s not in lost and now - sent_time[s] > est.rto]
        if newly_lost:
            for s in newly_lost:
                lost.add(s)
                pipe -= 1
            est.backoff()

            new_event = max(newly_lost) >= recovery_end
            #stalled-> nothing sent after the oldes expired packet has been acked
            #so network delivered nothing for a whole RTO
            stalled = (not fast) or largest_acked_tx < tx_of[min(newly_lost)]

            if fixed:
                record("lost")
            elif new_event:
                ssthresh = max(cwnd / 2, MIN_SSTHRESH)
                recovery_end = next_seq
                if stalled:
                    cwnd = 1.0                  # severe: restart with slow start
                    timeouts += 1
                    record("cut")
                else:
                    cwnd = ssthresh             # mild: later packets got through, so halve
                    fast_cuts += 1
                    record("fast_cut")
            elif stalled and any(retries[s] > 0 for s in newly_lost):
                cwnd = 1.0                      # a retransmission was lost and nothing arrives
                timeouts += 1
                record("cut")
            else:
                record("lost")

    elapsed = time.time() - start
    mode = f"fixed window={args.window}" if fixed else "cwnd"
    print(f"loss={loss:.0%}, window={mode}, sent {sent} packets, "
          f"{retransmit} retransmissions, {elapsed:.2f}s")
    if est.srtt is not None:
        print(f"final srtt={est.srtt * 1000:.1f} ms  rto={est.rto * 1000:.1f} ms  "
              f"timeout cuts={timeouts}  fast cuts={fast_cuts}  "
              f"max cwnd={max_cwnd_seen:.1f}  final ssthresh={ssthresh:.1f}")
    if log:
        log.close()



if __name__ == '__main__':
    main()