import argparse, socket, sys, time
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
    parsed.add_argument('--loss', type=float,  default = 0.0)
    parsed.add_argument('--window', type = int, default = 8)
    parsed.add_argument('--log', help = 'write RTT / ROT samples to this cv file')
    args = parsed.parse_args()

    addr = (args.host, args.port)
    loss, window = args.loss, args.window
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    est = RTTEstimator()

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

    if args.log:
        log = open(args.log, 'w')
    else: 
        log = None
    
    start = time.time()

    def record(event, sample=0.0):
        if log:
            log.write(f"{time.time() - start:.4f},{event},{sample:.5f},"
                      f"{est.srtt or 0:.5f},{est.rttvar or 0:.5f},{est.rto:.5f}\n")

    if log:
        log.write('time,event,sample,srtt,rttvar,rto\n')

    def transmit(seq):
        flags, payload = packets[seq]
        lossy_sendto(sock, ppack(flags, seq, 0, payload), addr, loss)
        sent_time[seq] = time.time()

    base = next_seq = 0
    sent = retransmit =timeouts = 0

    while base<total:
        #filling window
        while next_seq<min(window+base, total):
            transmit(next_seq)
            sent+=1
            next_seq+=1

        #read acks
        wait = 0.01
        for _ in range(256):
            socket.timeout(wait)
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
                if retries[ack] == 0: # Karn's rulel
                    sample = time.time() - sent_time[ack]
                    est.sample(sample)
                    record('sample', sample)
                while base<total and acked[base]:
                    base+=1

        #per packet timeouts
        now = time.time()

        expired = []
        for i in range(base, next_seq):
            if not acked[i] and (now-sent_time[i] > est.rto):
                expired.append(i)

        for e in expired:
            retries[e]+=1
            if retries[e]>=MAX_RETRIES:
                sys.exit(f'gave up on the packet {e}')
            transmit(e)
            retransmit+=1
        if expired:
            timeouts+=1
            est.backoff()
            record("timeout")

    elapsed = time.time() - start
    print(f"loss={loss:.0%}, window={window}, sent {sent} packets, "
          f"{retransmit} retransmissions, {elapsed:.2f}s")
    if est.srtt is not None:
        print(f"final srtt={est.srtt * 1000:.1f} ms  rttvar={est.rttvar * 1000:.1f} ms  "
              f"rto={est.rto * 1000:.1f} ms  timeout events={timeouts}")
    if log:
        log.close()



if __name__ == '__main__':
    main()