# ─── udp_backend.py ───────────────────────────────────────────
"""
UDP Control Channel Manager for DIY EEG Board

This module handles the control/command channel over UDP:
- Auto-discovery of board IP via beacon
- Bidirectional command/response communication
- Periodic keep-alive ("floof") messages
- Thread-safe operation with queues

Note: This is separate from the high-speed data channel (port 5001)
"""

import socket
import threading
import queue
import time
from typing import Optional, Callable


class UDPManager:
    """
    Manages UDP control communication with the EEG board.
    
    The protocol works as follows:
    1. Board sends a beacon packet to announce its presence
    2. Manager locks onto board's IP address
    3. Bidirectional command/response communication begins
    4. Periodic "floof" keep-alive maintains connection
    
    Thread-safe: All communication goes through queues.
    """
    
    # ────────── Configuration Constants ──────────
    FLOOF_INTERVAL = 5.0    # Keep-alive interval in seconds
    SOCKET_TIMEOUT = 0.050  # 50ms - balance between CPU and responsiveness
    RECV_BUFFER_SIZE = 512  # Max size for control messages
    MAX_TX_PER_CYCLE = 20   # Process up to N TX messages per loop
    
    def __init__(self, ctrl_port: int):
        """
        Initialize UDP manager.
        
        Args:
            ctrl_port: UDP port to listen on (typically 5000)
        """
        # Network configuration
        self.ctrl_port = ctrl_port
        self.board_ip: Optional[str] = None  # Discovered from first packet
        
        # Communication queues
        self.rx_q = queue.Queue()  # Received messages for GUI display
        self.tx_q = queue.Queue()  # Messages to transmit
        
        # Optional callback for transmitted messages (GUI echo)
        self.tx_hook: Optional[Callable[[str], None]] = None
        
        # Thread control
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        
        # State tracking
        self._is_running = False

    # ────────────────────── Public API ──────────────────────

    def start(self) -> None:
        """
        Start the UDP communication thread.
        
        Safe to call multiple times - will not create duplicate threads.
        """
        if self._thread and self._thread.is_alive():
            return  # Already running
            
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="UDPControlThread"
        )
        self._thread.start()
        self._is_running = True

    def stop(self) -> None:
        """
        Stop the UDP communication thread.
        
        Waits up to 0.5 seconds for clean shutdown.
        """
        if not self._thread:
            return
            
        self._stop_evt.set()
        self._is_running = False
        
        # Wait for thread to exit
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)
            if self._thread.is_alive():
                self.rx_q.put("[PC] ⚠ UDP thread failed to stop cleanly\n")

    def send(self, text: str) -> None:
        """
        Queue a control command for transmission.
        
        Args:
            text: Command text (newline will be added automatically)
            
        Note: Commands are only sent after board IP is discovered.
        """
        # Clean up the command
        line = text.rstrip()
        
        # Encode and add protocol newline
        self.tx_q.put(line.encode('ascii', errors='ignore') + b"\n")

    def is_connected(self) -> bool:
        """Check if connected to a board (IP discovered)."""
        return self.board_ip is not None

    # ────────────────────── Internal Loop ──────────────────────

    def _loop(self) -> None:
        """
        Main worker thread loop.
        
        Handles:
        - Receiving packets and board discovery
        - Transmitting queued commands
        - Sending periodic keep-alive messages
        """
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Allow port reuse (helpful during development)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Bind to all interfaces on control port
        sock.bind(("", self.ctrl_port))
        
        # Set timeout for blocking receive
        sock.settimeout(self.SOCKET_TIMEOUT)
        
        # Initialize keep-alive timer
        next_floof = time.time() + self.FLOOF_INTERVAL
        
        # Log startup
        self.rx_q.put(f"[PC] UDP listening on *:{self.ctrl_port}\n")

        # Main communication loop
        while not self._stop_evt.is_set():
            
            # ─────── 1) Receive Packets ───────
            # This blocks for up to SOCKET_TIMEOUT seconds
            # No CPU spinning - kernel handles the wait efficiently
            try:
                data, addr = sock.recvfrom(self.RECV_BUFFER_SIZE)
                
                # Decode message (control protocol is text-based)
                try:
                    line = data.decode('ascii', errors='replace').strip()
                except UnicodeDecodeError:
                    line = f"[BINARY DATA: {data.hex()}]"
                
                # Add to receive queue with ESP prefix
                self.rx_q.put(f"[ESP] {line}\n")
                
                # Board discovery - lock onto first sender
                if self.board_ip is None:
                    self.board_ip = addr[0]
                    self.rx_q.put(f"[PC] ✓ Board discovered at {self.board_ip}\n")
                    
                # Handle IP changes (board reset with new IP)
                elif addr[0] != self.board_ip:
                    self.rx_q.put(f"[PC] ⚠ Board IP changed: {self.board_ip} → {addr[0]}\n")
                    self.board_ip = addr[0]
                    
            except socket.timeout:
                # Normal - no data received within timeout
                pass
            except socket.error as e:
                # Network error
                self.rx_q.put(f"[PC] Socket error: {e}\n")
            except Exception as e:
                # Unexpected error
                self.rx_q.put(f"[PC] Unexpected error in RX: {e}\n")

            # ─────── 2) Transmit Queued Commands ───────
            # Process all pending TX messages (with limit to prevent blocking)
            tx_count = 0
            while tx_count < self.MAX_TX_PER_CYCLE:
                try:
                    pkt = self.tx_q.get_nowait()
                    
                    # Only send if we know the board's IP
                    if self.board_ip:
                        # Optional echo callback for GUI
                        if self.tx_hook:
                            try:
                                msg = pkt.decode('ascii', errors='replace').rstrip()
                                self.tx_hook(msg)
                            except Exception:
                                pass  # Don't let callback errors stop transmission
                        
                        # Send to board
                        sock.sendto(pkt, (self.board_ip, self.ctrl_port))
                        tx_count += 1
                    else:
                        # No board IP yet - put message back
                        self.tx_q.put(pkt)
                        break
                        
                except queue.Empty:
                    break  # No more messages to send
                except socket.error as e:
                    self.rx_q.put(f"[PC] Failed to send: {e}\n")
                    break

            # ─────── 3) Keep-Alive ("floof") ───────
            now = time.time()
            if self.board_ip and now >= next_floof:
                try:
                    # Send keep-alive
                    if self.tx_hook:
                        self.tx_hook("floof")
                    sock.sendto(b"floof", (self.board_ip, self.ctrl_port))
                    
                    # Schedule next keep-alive
                    next_floof = now + self.FLOOF_INTERVAL
                    
                except socket.error:
                    # Keep-alive failed - board might be down
                    pass

        # ─────── Cleanup ───────
        try:
            sock.close()
        except Exception:
            pass
            
        self.rx_q.put("[PC] UDP worker stopped\n")


# ────────────────────── Usage Example ──────────────────────
"""
Example usage in GUI:

    # Create and start UDP manager
    udp = UDPManager(ctrl_port=5000)
    udp.start()
    
    # Set up TX echo callback
    udp.tx_hook = lambda msg: console.insert("end", f">>> {msg}\\n")
    
    # Send commands
    udp.send("sys filters_on")
    udp.send("sys digitalgain 8")
    
    # Check connection
    if udp.is_connected():
        print(f"Connected to board at {udp.board_ip}")
    
    # Process received messages
    while not udp.rx_q.empty():
        msg = udp.rx_q.get()
        console.insert("end", msg)
    
    # Stop when done
    udp.stop()
"""