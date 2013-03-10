#!/usr/bin/env python

from random import choice, shuffle
from subprocess import Popen, PIPE
from mininet.util import pmonitor
from time import time, sleep
import sys
import termcolor as T
from mininet.cli import CLI
from collections import defaultdict, Counter
from util.helper import *

def progress(t):
    while t > 0:
        print T.colored('  %3d seconds left       \r' % (t), 'cyan'),
        t -= 1
        sys.stdout.flush()
        sleep(1)
    print '\r\n'

class OneToOneWorkload():
    def __init__(self, net, iperf, seconds):
        self.iperf = iperf
        self.seconds = seconds
        self.mappings = []
        self.net = net
        hosts = list(net.hosts)
        shuffle(hosts)
        group1, group2 = hosts[::2], hosts[1::2]
        self.create_mappings(list(group1), list(group2))
        self.create_mappings(group2, group1)

    def create_mappings(self, group1, group2):
        while group1:
            server = choice(group1)
            group1.remove(server)
            client = choice(group2)
            group2.remove(client)
            self.mappings.append((server, client))

    def run(self, output_dir):
        for mapping in self.mappings:
            server = mapping[0]
            server.popen("%s -s -p %s > %s/server_iperf-%s.txt" %
                         (self.iperf, 5001, output_dir, server.name), shell=True)
        Popen('mpstat 2 %d > %s/cpu_utilization.txt' % (self.seconds/2 + 2, output_dir), shell=True)
        procs = []
        for mapping in self.mappings:
            server, client = mapping
            procs.append(client.popen("%s -c %s -p %s -t %d -yc -i 10 > %s/client_iperf-%s.txt" %
                                      (self.iperf, server.IP(), 5001, self.seconds, output_dir, client.name),
                                      shell=True))
            client.popen("ping -c 12 -i 5 %s > %s/client_ping-%s.txt"
                         % (server.IP(), output_dir, client.name), shell=True)

        interfaces = []
        for node in self.net.switches:
            for intf in node.intfList():
                if intf.link:
                    interfaces.append(intf.link.intf1.name)
                    interfaces.append(intf.link.intf2.name)
        #wait until established, or take samples over whole test after established
        get_rates(interfaces, output_dir)

        progress(self.seconds + 5) # 5 second buffer to tear down connections and write output
        for proc in procs:
            proc.communicate()

def get_txbytes(iface):
    f = open('/proc/net/dev', 'r')
    lines = f.readlines()
    for line in lines:
        if iface in line:
            break
    f.close()
    if not line:
        raise Exception("could not find iface %s in /proc/net/dev:%s" %
                        (iface, lines))
    # Extract TX bytes from:                                                           
    #Inter-|   Receive                                                |  Transmit      
    # face |bytes    packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed                                                   
# lo: 6175728   53444    0    0    0     0          0         0  6175728   53444 0    0    0     0       0          0                                                          
    return float(line.split()[9])

NSAMPLES = 3
SAMPLE_PERIOD_SEC = 1.0
SAMPLE_WAIT_SEC = 3.0

def get_rates(ifaces, output_dir, nsamples=NSAMPLES, period=SAMPLE_PERIOD_SEC,
              wait=SAMPLE_WAIT_SEC):
    """Returns the interface @iface's current utilization in Mb/s.  It                 
    returns @nsamples samples, and each sample is the average                          
    utilization measured over @period time.  Before measuring it waits                 
    for @wait seconds to 'warm up'."""
    # Returning nsamples requires one extra to start the timer.                        
    nsamples += 1
    last_time = 0
    last_txbytes = Counter()
    ret = []
    sleep(wait)
    txbytes = Counter()
    ret = defaultdict(list)
    while nsamples:
        nsamples -= 1
        for iface in ifaces:
            txbytes[iface] = get_txbytes(iface)
        now = time()
        elapsed = now - last_time
        #if last_time:                                                                 
        #    print "elapsed: %0.4f" % (now - last_time)                                
        last_time = now
        # Get rate in Mbps; correct for elapsed time.
        for iface in txbytes:
            rate = (txbytes[iface] - last_txbytes[iface]) * 8.0 / 1e6 / elapsed
            if last_txbytes[iface] != 0:
                # Wait for 1 second sample
                ret[iface].append(rate)
        last_txbytes = txbytes.copy()
        print '.',
        sys.stdout.flush()
        sleep(period)
    f = open("%s/link_util.txt" % output_dir, 'w')
    for iface in ret:
        f.write("%f\n" % avg(ret[iface]))
    f.close()
