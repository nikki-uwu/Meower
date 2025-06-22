import RPi.GPIO as GPIO
import matplotlib.pyplot as plt
import numpy as np
import spidev
import time
import socket
import threading
from queue import Queue

from collections import deque




# Helper functions
# --------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------
# SPI write read but controlling chips selects so we can talk to devices eparately or to all at ones
def xfer(spi, master_cs, slave_cs, data, target):
    # Set chip select pins based on target
    if target == "master":
        GPIO.output(master_cs, GPIO.LOW )  # Select master
        GPIO.output(slave_cs , GPIO.HIGH)  # Deselect slave
    elif target == "slave":
        GPIO.output(master_cs, GPIO.HIGH)  # Deselect master
        GPIO.output(slave_cs , GPIO.LOW )  # Select slave
    elif target == "both":
        GPIO.output(master_cs, GPIO.LOW)   # Select master
        GPIO.output(slave_cs , GPIO.LOW)   # Select slave
    else:
        GPIO.output(master_cs, GPIO.HIGH)  # Deselect master
        GPIO.output(slave_cs , GPIO.HIGH)  # Deselect slave
    
    # Perform SPI transfer
    received = spi.xfer2(data)
    
    # Deselect both pins after transfer
    GPIO.output(master_cs, GPIO.HIGH)
    GPIO.output(slave_cs , GPIO.HIGH)
    
    # return data received from device
    return received

# UDP client thread which will work as separate thread
def sending_thread(packet_queue, sock):
    """
    Runs in a separate thread to continuously send data packets from a queue via UDP.
    This function never stops unless the program terminates or the thread is killed.
    """
    while True:
        # Get the next data packet from the queue (blocks if queue is empty)
        data = packet_queue.get()
        
        # Send the data immediately via UDP to the target IP and port
        # "192.168.137.1" is the destination IP address, 5555 is the port number
        sock.sendto(data, ("192.168.137.1", 5555))
        
        # Mark this packet as processed, updating the queue's task counter
        # This helps other parts of the program know this task is complete
        packet_queue.task_done()

# Reset on start of the ADCs
def ads1299_full_reset(reset_pin, pwdn_pin):
    """
    Perform a full reset of the ADS1299 chip using the specified RESET and PWDN GPIO pins.
    
    This function ensures a complete reset regardless of the previous pin states by:
    - Setting PWDN high to power up the chip (and keep it high, as requested).
    - Waiting for the power-up stabilization time.
    - Toggling RESET low then high to reset the digital logic.
    - Waiting for the chip to initialize fully.
    
    Assumes:
    - GPIO pins are already configured as outputs.
    - GPIO mode is set to BCM numbering.
    
    Args:
        reset_pin (int): GPIO pin number connected to the ADS1299 RESET pin.
        pwdn_pin (int): GPIO pin number connected to the ADS1299 PWDN pin.
    """
    # Set PWDN low to fully stop ADCs
    GPIO.output(pwdn_pin, GPIO.LOW)
    # Wait 100 ms for power-down stabilization
    time.sleep(0.1)

    # Set PWDN high to ensure the chip is powered up and remains so
    GPIO.output(pwdn_pin, GPIO.HIGH)
    # Wait 100 ms for power-up stabilization (datasheet typical: 50 ms)
    time.sleep(0.1)
    
    # Pull RESET low to start the reset (active low)
    GPIO.output(reset_pin, GPIO.LOW)
    # Wait 1 ms, exceeding the minimum 18 clock cycles (~8.79 us at 2.048 MHz)
    time.sleep(0.001)
    
    # Pull RESET high to complete the reset
    GPIO.output(reset_pin, GPIO.HIGH)
    # Wait 130 ms for initialization (2^18 clock cycles, ~128 ms at 2.048 MHz)
    time.sleep(0.13)




# Network setup
# --------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------
# Create UDP socket
PC_PORT = 5555
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Increase send buffer in case data is generated quickly
sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024*1024)

# We use a thread+queue so that reading from the ADC won't block
# if send buffers temporarily fill up.
packet_queue = Queue()

# Start the sending thread in the background (daemon = True)
# Create the thread, passing arguments via 'args'
thread = threading.Thread(target = sending_thread      , # The function to run
                          args   = (packet_queue, sock), # Arguments as a tuple
                          daemon = True                ) # Make it a daemon thread

# Start the thread
thread.start()




# GPIO and SPI setup
# --------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------
# Set GPIO pins
DRDY_PIN      = 17 # physical pin 11
START_PIN     = 22 # physical pin 15
RESET_PIN     = 13 # physical pin 33
PWDN_PIN      = 26 # physical pin 37
CS_MASTER_PIN = 25 # physical pin 22
CS_SLAVE_PIN  =  5 # physical pin 29
GPIO.setmode(GPIO.BCM)
GPIO.setup(DRDY_PIN     , GPIO.IN)
GPIO.setup(START_PIN    , GPIO.OUT, initial = GPIO.LOW ) # Set START pin to low right away
GPIO.setup(RESET_PIN    , GPIO.OUT, initial = GPIO.LOW ) # Set RESET pin to low right away
GPIO.setup(PWDN_PIN     , GPIO.OUT, initial = GPIO.LOW ) # Set PWDN  pin to low right away
GPIO.setup(CS_MASTER_PIN, GPIO.OUT, initial = GPIO.HIGH) # Set ChipSelect pin for master to high (off) right away
GPIO.setup(CS_SLAVE_PIN , GPIO.OUT, initial = GPIO.HIGH) # Set ChipSelect pin for slave to high (off) right away

# SPI setup for master and slave
spi = spidev.SpiDev()
spi.open(0, 0) # Open SPI bus 0, device 0 (CE0)
spi.mode = 1   # SPI Mode 1 (CPOL = 0, CPHA = 1)
spi.max_speed_hz = 2000000 # 2 MHz closk speed
bytes_per_frame  = 54 # (3 status + [8 channels * 3 bytes]) x 2ADCs




# ADC config
# --------------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------------
# Full reset at the beginning
ads1299_full_reset(RESET_PIN, PWDN_PIN)

# Reset Registers to Default Values for both ADCs
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x06], 'both') # Datasheet - 9.5.3 SPI command definitions, p.40

# Stop continious data mode (SDATAC)
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x11], 'both') # Datasheet - 9.5.3 SPI command definitions, p.40

# Stop conversion just in case (STOP)
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x0A], 'both') # Datasheet - 9.5.3 SPI command definitions, p.40

# Read ID
ID_check_master = xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x20, 0x00, 0x00], 'master') # Datasheet - 9.5.3.10 PREG, p.43

# Set reference and check it
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x43, 0x00, 0xE0], 'both')
Ref_check = xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x23, 0x00, 0x00], 'master')

# Configuration 1 - Daisy-chain, reference clock, sample rate)
# Bit structure
# bit 7        | 6                  | 5                 | 4        | 3        | 2   | 1   | 0
# use Always 1 | Daisy-chain enable | Clock output mode | always 1 | always 0 | DR2 | DR1 | DR0
#                 76543210
#                 1XY10ZZZ
Master_conf_1 = 0b10110110 # Daisy is ON, Internal Clock output is  ON, 250 SPS
Slave_conf_1  = 0b10010110 # Daisy is ON, Internal Clock output is OFF, 250 SPS

# Send configuration messages
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x41, 0x00, Master_conf_1], 'master')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x41, 0x00, Slave_conf_1 ], 'slave' )
Daisy_check = xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x21, 0x00, 0x00], 'master')

# Configuration 2 - Test signal settings
# Bit structure
# bit 7        | 6        | 5        | 4                   | 3        | 2                  | 1           0
# use Always 1 | Always 1 | Always 0 | Test source ext/int | Always 0 | Test sig amplitude | Test sig greq
#                 76543210
#                 110X0YZZ
Master_conf_2 = 0b11010000
Slave_conf_2  = 0b11010010

# Send configuration messages
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x42, 0x00, Master_conf_2], 'master')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x42, 0x00, Slave_conf_2 ], 'slave' )
TestSig_check = xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x22, 0x00, 0x00], 'master')

# Configuration 3 - Reference and bias
# Bit structure
# bit 7                | 6        | 5        | 4         | 3                | 2                  | 1                      | 0 read only
# use Power ref buffer | Always 1 | Always 1 | BIAS meas | BIAS ref ext/int | BIAS power Down/UP | BIAS sence lead OFF/ON | LEAD OFF status
#                 76543210
#                 X11YZMKR
Master_conf_3 = 0b11100000 # Daisy is ON, Internal Clock output is  ON, 250 SPS
Slave_conf_3  = 0b11100000 # Daisy is ON, Internal Clock output is OFF, 250 SPS
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x43, 0x00, Master_conf_3], 'master')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x43, 0x00, Slave_conf_3 ], 'slave' )
RefBias_check = xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x23, 0x00, 0x00], 'master')

# Configuration 4 - Channels settings
# bit 7                 | 6 5 4 | 3                | 2 1 0 
# use Power down On/Off | GAIN  | SRB2 open/closed | Channel input
#                76543210
Channel_conf = 0b00000100 # 0b01100101 - power on, PGA gain 24, SRB2 off, input test signals
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x45, 0x00, Channel_conf], 'both')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x46, 0x00, Channel_conf], 'both')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x47, 0x00, Channel_conf], 'both')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x48, 0x00, Channel_conf], 'both')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x49, 0x00, Channel_conf], 'both')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x4A, 0x00, Channel_conf], 'both')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x4B, 0x00, Channel_conf], 'both')
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x4C, 0x00, Channel_conf], 'both')

# Start signal
GPIO.output(START_PIN, GPIO.HIGH)

# RDATAC
xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x10], 'both')

try:
    while True:
        if GPIO.input(DRDY_PIN) == 0:
            # Get one Frame from ADC
            raw_data = xfer(spi, CS_MASTER_PIN, CS_SLAVE_PIN, [0x00] * bytes_per_frame, 'both')
            
            packet_queue.put(bytes(raw_data))

except KeyboardInterrupt:
    pass
