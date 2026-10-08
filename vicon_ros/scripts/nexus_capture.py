#!/usr/bin/env python3
"""Send UDP start/stop capture commands to Vicon Nexus.

Based on the official Vicon UDP capture example:
  - Stop packets must include Name, DatabasePath, and PacketID.
  - A null terminator is appended to the payload (as in the C++ SDK example).
  - Socket uses SO_BROADCAST to match official behaviour.

  On the Nexus software:
      - To allow this feature to work
      -> Go to the "Trial Recording" Tool Tab
      -> Auto Capture Setup
      -> Show Advanced (settings)
      -> Check Start/Stopover network: [Recieve]
      -> Address [All] : 3030
      -> [Arm] [Lock]

Usage:
  python3 nexus_capture.py start --trial-name TEST01 --path "C:/Temp"
  python3 nexus_capture.py stop  --trial-name TEST01 --path "C:/Temp"
"""

import socket
import argparse
import random


START_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<CaptureStart>
  <Name VALUE="{trial_name}"/>
  <Notes VALUE=""/>
  <Description VALUE=""/>
  <DatabasePath VALUE="{database_path}"/>
  <Delay VALUE="0"/>
  <PacketID VALUE="{packet_id}"/>
</CaptureStart>
"""

STOP_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<CaptureStop>
  <Name VALUE="{trial_name}"/>
  <DatabasePath VALUE="{database_path}"/>
  <PacketID VALUE="{packet_id}"/>
</CaptureStop>
"""


def send_capture_command(host, port, xml_payload):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    # Include null terminator — matches the official C++ example
    sock.sendto(xml_payload.encode("utf-8") + b"\x00", (host, port))
    sock.close()
    print(f"Sent to {host}:{port}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Control Vicon Nexus capture over UDP")
    parser.add_argument("action", choices=["start", "stop"])
    parser.add_argument("--host", default="192.168.10.1", help="Nexus machine IP")
    parser.add_argument("--port", type=int, default=3030, help="Nexus UDP port")
    parser.add_argument("--trial-name", default="Trial", help="Trial name (required by Nexus)")
    parser.add_argument("--path", default="", help="Database capture path (required by Nexus)")
    parser.add_argument("--packet-id", type=int, default=None, help="Packet ID (random if not set)")
    args = parser.parse_args()

    if args.action == "start":
        payload = START_XML.format(
            trial_name=args.trial_name,
            database_path=args.path,
            packet_id=args.packet_id if args.packet_id is not None else random.randint(0, 999999),
        )
    else:
        payload = STOP_XML.format(
            trial_name=args.trial_name,
            database_path=args.path,
            packet_id=args.packet_id if args.packet_id is not None else random.randint(0, 999999),
        )

    send_capture_command(args.host, args.port, payload)
