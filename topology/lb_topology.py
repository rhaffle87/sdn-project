#!/usr/bin/env python3
"""
Custom Multi-Path Mininet Topology for SDN Load Balancer & Traffic Engineering
Topology Layout (Diamond Mesh):
                  +-------------+
                  |  Switch s2  | (Upper Path A)
         +------->| (Core/Transit)|--------+
         |        +-------------+        |
         |                               |
  +------+------+                 +------v------+
  |  Switch s1  |                 |  Switch s4  |
  |  (Ingress)  |                 |  (Egress)   |
  +------+------+                 +------+------+
         |                               ^
         |        +-------------+        |
         +------->|  Switch s3  |--------+
                  | (Core/Transit)| (Lower Path B)
                  +-------------+

Clients connected to s1:
  - h1: 10.0.0.1 (MAC 00:00:00:00:00:01)
  - h2: 10.0.0.2 (MAC 00:00:00:00:00:02)

Backend Servers connected to s4:
  - s1_srv: 10.0.0.11 (MAC 00:00:00:00:00:11)
  - s2_srv: 10.0.0.12 (MAC 00:00:00:00:00:12)
  - s3_srv: 10.0.0.13 (MAC 00:00:00:00:00:13)
  - s4_srv: 10.0.0.14 (MAC 00:00:00:00:00:14)

Virtual IP (VIP): 10.0.0.100 (Virtual MAC 00:00:00:00:00:fe)
"""

import argparse
import os
import sys
import time
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.topo import Topo

class DiamondLBTopo(Topo):
    """Diamond Multi-Path Topology with Redundant Core Links."""

    def build(self):
        # 1. Add OpenFlow 1.3 OVS Switches
        s1 = self.addSwitch('s1', dpid='0000000000000001', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', dpid='0000000000000002', protocols='OpenFlow13')
        s3 = self.addSwitch('s3', dpid='0000000000000003', protocols='OpenFlow13')
        s4 = self.addSwitch('s4', dpid='0000000000000004', protocols='OpenFlow13')

        # 2. Add Client Hosts (connected to Ingress Switch s1)
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
        self.addLink(h1, s1, cls=TCLink, bw=20, delay='1ms')
        self.addLink(h2, s1, cls=TCLink, bw=20, delay='1ms')

        # 3. Add Backend Server Hosts (connected to Egress Switch s4)
        s1_srv = self.addHost('s1_srv', ip='10.0.0.11/24', mac='00:00:00:00:00:11')
        s2_srv = self.addHost('s2_srv', ip='10.0.0.12/24', mac='00:00:00:00:00:12')
        s3_srv = self.addHost('s3_srv', ip='10.0.0.13/24', mac='00:00:00:00:00:13')
        s4_srv = self.addHost('s4_srv', ip='10.0.0.14/24', mac='00:00:00:00:00:14')

        self.addLink(s1_srv, s4, cls=TCLink, bw=20, delay='1ms')
        self.addLink(s2_srv, s4, cls=TCLink, bw=20, delay='1ms')
        self.addLink(s3_srv, s4, cls=TCLink, bw=20, delay='1ms')
        self.addLink(s4_srv, s4, cls=TCLink, bw=20, delay='1ms')

        # 4. Add Redundant Switch-to-Switch Core Links (Traffic Engineering Paths)
        # Upper Path A: s1 <-> s2 <-> s4 (10 Mbps, 2ms delay)
        self.addLink(s1, s2, cls=TCLink, bw=10, delay='2ms', max_queue_size=100)
        self.addLink(s2, s4, cls=TCLink, bw=10, delay='2ms', max_queue_size=100)

        # Lower Path B: s1 <-> s3 <-> s4 (10 Mbps, 2ms delay)
        self.addLink(s1, s3, cls=TCLink, bw=10, delay='2ms', max_queue_size=100)
        self.addLink(s3, s4, cls=TCLink, bw=10, delay='2ms', max_queue_size=100)

def start_backend_servers(net, project_root):
    """Launch Flask backend microservice on each backend host."""
    # Configure management interface on root namespace so controller can probe backends
    os.system("sudo ip addr add 10.0.0.254/24 dev s4 2>/dev/null || true")
    os.system("sudo ip link set s4 up 2>/dev/null || true")

    server_script = os.path.join(project_root, "server", "backend_server.py")
    python_bin = sys.executable

    servers = [
        ("s1_srv", "srv1", 80),
        ("s2_srv", "srv2", 80),
        ("s3_srv", "srv3", 80),
        ("s4_srv", "srv4", 80),
    ]

    info("*** Starting Flask backend servers...\n")
    for host_name, srv_id, port in servers:
        host = net.get(host_name)
        log_file = f"/tmp/{srv_id}.log"
        cmd = f"{python_bin} {server_script} --id {srv_id} --port {port} > {log_file} 2>&1 &"
        info(f"    Starting {srv_id} on {host.IP()}:{port}\n")
        host.cmd(cmd)

    # Allow servers 1.5 seconds to bind
    time.sleep(1.5)
    info("*** All 4 backend servers running.\n")

def run(start_servers=True, interactive=True):
    """Instantiate and run the Mininet topology."""
    setLogLevel('info')
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    topo = DiamondLBTopo()
    net = Mininet(
        topo=topo,
        switch=OVSSwitch,
        controller=None,
        autoSetMacs=False,
        autoStaticArp=False
    )

    info("*** Adding Remote Ryu Controller (127.0.0.1:6653)...\n")
    c0 = net.addController(
        'c0',
        controller=RemoteController,
        ip='127.0.0.1',
        port=6653
    )

    net.start()
    info("*** Network started.\n")

    # Configure management interface on root namespace so controller can probe backends
    os.system("sudo ip addr add 10.0.0.254/24 dev s4 2>/dev/null || true")
    os.system("sudo ip link set s4 up 2>/dev/null || true")

    if start_servers:
        start_backend_servers(net, project_root)

    info("\n=======================================================\n")
    info("  SDN Load Balancer & Traffic Engineering Topology     \n")
    info("  Ingress Switch: s1 (Clients h1, h2)                 \n")
    info("  Transit Switches: s2 (Path A), s3 (Path B)           \n")
    info("  Egress Switch:  s4 (Backends s1_srv .. s4_srv)      \n")
    info("  VIP Service:    10.0.0.100 (MAC 00:00:00:00:00:fe)   \n")
    info("=======================================================\n\n")

    if interactive:
        CLI(net)
        info("*** Stopping network and killing server processes...\n")
        os.system("sudo pkill -f backend_server.py 2>/dev/null || true")
        net.stop()

    return net

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Mininet Diamond LB Topology")
    parser.add_argument('--no-servers', action='store_true', help="Do not auto-start backend servers")
    parser.add_argument('--no-cli', action='store_true', help="Do not open Mininet interactive CLI")
    args = parser.parse_args()

    if not args.no_cli:
        run(start_servers=not args.no_servers, interactive=True)
    else:
        net = run(start_servers=not args.no_servers, interactive=False)
        info("*** Network running in daemon mode. Press Ctrl+C to terminate...\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            info("*** Stopping network and killing server processes...\n")
            os.system("sudo pkill -f backend_server.py 2>/dev/null || true")
            net.stop()

