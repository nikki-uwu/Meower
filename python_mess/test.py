# -*- coding: utf-8 -*-
"""
Created on Sat Mar 29 02:06:53 2025

@author: manok
"""

import socket
import select
import sys

def flush_udp_socket(sock):
    sock.setblocking(False)
    try:
        while True:
            sock.recv(65535)  # discard immediately
    except BlockingIOError:
        pass
    finally:
        sock.setblocking(True)

# Configuration
ESP_IP = "192.168.137.32"  # Replace with your ESP32's IP address
PC_IP = "0.0.0.0"         # Listen on all interfaces
RECEIVE_PORT = 5001       # Port to receive data from ESP32
SEND_PORT = 5000          # Port to send commands to ESP32

# Create receiving socket
receive_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
receive_sock.bind((PC_IP, RECEIVE_PORT))

# Create sending socket
send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print("Ready to send and receive. Type commands to send to ESP32 (type 'exit' to quit):")

#send_sock.sendto(('SPI_SR 3 3 0x20 0x00 0x00' + ' ').encode(), (ESP_IP, 5000))
send_sock.sendto(('SPI_SR 3 3 0x43 0x57 0xFA' + ' ').encode(), (ESP_IP, 5000))
#send_sock.sendto(('START_CONT' + ' ').encode(), (ESP_IP, 5000))
#send_sock.sendto(('STOP_CONT' + ' ').encode(), (ESP_IP, 5000))
receive_sock.recvfrom(1024)


#flush_udp_socket(receive_sock)
