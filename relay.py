import argparse #to write user-friendly command-line interfaces
#trying to learn it instead of sys
import signal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('listen_port', type=int)
    parser.add_argument('dest_host')
    parser.add_argument('dest_port', type=int)
    parser.add_argument('--rate', type = float, default=200, help = 'bottleneck speed, packets/second')
    parser.add_argument('--queue', type = int, default=20, help='queue capacity in packets')
    parser.add_argument('--delay',type=float,default=0.02, help='one-way delay, seconds')
    parser.add_argument('--loss', type=float, default=0.0, help='random loss')
    parser.add_argument('--log', help-'wirte time, queue_len, droppped')

    args = parser.parse_args()

    def stop(*_):
        raise KeyboardInterrupt
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, stop)