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