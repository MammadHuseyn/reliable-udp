import argparse, socket, sys, time
from rudp import *

#RTO - retransmission timeout
#RTT - round trip time
#SRTT - smoothed round trip time
#RTTVAR - RTT variation, measure of jitter. how much RTT fluctues form SRTT

#Initial
#SRTT = RTT
#RTTVAR = RTT / 2
#RTO = SRTT + max(Clock_G, K * RTTVAR)

#RTTVAR = (1 - beta) * RTTVAR + beta * abs(SRTT - RTT)
#SRTT = (1 - alpha) * SRTT + alpha * RTT
#RTO = SRTT + max(Clock_G, K * RTTVAR)

INITIAL_RTO = 0.5
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