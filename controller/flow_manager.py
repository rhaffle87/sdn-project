"""
Flow Manager: OpenFlow 1.3 Flow Modification and Packet Generation Helpers
Encapsulates low-level Ryu ofproto_v1_3 operations into clean, reusable functions.
"""

from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, arp

def add_flow(datapath, priority, match, actions, idle_timeout=0, hard_timeout=0, buffer_id=None):
    """
    Install an OpenFlow 1.3 flow rule into the switch's flow table.
    """
    ofproto = datapath.ofproto
    parser = datapath.ofproto_parser

    # Build instruction set containing apply-actions
    inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

    if buffer_id is not None and buffer_id != ofproto.OFP_NO_BUFFER:
        mod = parser.OFPFlowMod(
            datapath=datapath,
            buffer_id=buffer_id,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
            flags=ofproto.OFPFF_SEND_FLOW_REM
        )
    else:
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=inst,
            idle_timeout=idle_timeout,
            hard_timeout=hard_timeout,
            flags=ofproto.OFPFF_SEND_FLOW_REM
        )
    datapath.send_msg(mod)

def delete_flow(datapath, match=None, priority=None):
    """
    Remove flow entries matching given criteria from the switch.
    """
    ofproto = datapath.ofproto
    parser = datapath.ofproto_parser

    match = match or parser.OFPMatch()
    priority = priority or 0

    mod = parser.OFPFlowMod(
        datapath=datapath,
        command=ofproto.OFPFC_DELETE,
        out_port=ofproto.OFPP_ANY,
        out_group=ofproto.OFPG_ANY,
        priority=priority,
        match=match
    )
    datapath.send_msg(mod)

def send_packet_out(datapath, buffer_id, in_port, actions, data=None):
    """
    Send an OFPPacketOut message from controller to datapath.
    """
    ofproto = datapath.ofproto
    parser = datapath.ofproto_parser

    if buffer_id is None:
        buffer_id = ofproto.OFP_NO_BUFFER

    out = parser.OFPPacketOut(
        datapath=datapath,
        buffer_id=buffer_id,
        in_port=in_port,
        actions=actions,
        data=data
    )
    datapath.send_msg(out)

def send_arp_reply(datapath, port, src_mac, src_ip, dst_mac, dst_ip):
    """
    Construct and send an ARP reply packet directly out a designated switch port.
    Used for VIP ARP resolution without hitting backend hosts.
    """
    pkt = packet.Packet()
    # Ethernet header
    pkt.add_protocol(ethernet.ethernet(
        ethertype=0x0806,  # ARP
        dst=dst_mac,
        src=src_mac
    ))
    # ARP reply payload
    pkt.add_protocol(arp.arp(
        opcode=arp.ARP_REPLY,
        src_mac=src_mac,
        src_ip=src_ip,
        dst_mac=dst_mac,
        dst_ip=dst_ip
    ))
    pkt.serialize()

    parser = datapath.ofproto_parser
    actions = [parser.OFPActionOutput(port)]
    send_packet_out(datapath, None, datapath.ofproto.OFPP_CONTROLLER, actions, data=pkt.data)
