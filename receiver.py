import socket, time
from rudp import *

def recv_all(sock, loss=0.0):
    excepted = 0
    out = []

    while True:
        raw, addr,