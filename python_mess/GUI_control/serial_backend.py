# ─── serial_backend.py ───────────────────────────────────────────
"""
Serial Communication Manager for DIY EEG Board

This module handles all serial port communication with the EEG board:
- Auto-reconnection on disconnect
- Thread-safe command queuing
- Synchronous command/response with send_and_wait()
- Graceful degradation if PySerial not installed
"""

import threading
import queue
import time
from typing import Optional, List

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None  # Demo-mode fallback when PySerial not installed


class SerialManager:
    """
    Manages serial communication in a separate thread.
    
    Features:
    - Non-blocking operation via queues
    - Automatic reconnection on disconnect
    - Echo commands to console for visibility
    - Wait for acknowledgments with timeout
    """
    
    # Constants
    RETRY_INTERVAL = 0.2      # Seconds between reconnection attempts
    READ_TIMEOUT = 0.1        # Serial read timeout (prevents blocking)
    DEFAULT_ACK_TIMEOUT = 1.0 # Default timeout for send_and_wait()

    def __init__(self):
        """Initialize queues and threading primitives."""
        # Queue for data received from serial port (displayed in console)
        self.rx_q = queue.Queue()
        
        # Queue for data to be transmitted to serial port
        self.tx_q = queue.Queue()
        
        # Special queue for ACK/NACK responses (OK/ERR messages)
        self.ack_q = queue.Queue()
        
        # Thread control
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        
        # Connection state (could be exposed as property if needed)
        self._is_connected = False

    # ────────────────────── Public API ──────────────────────────

    def start(self, port: str, baud: int) -> None:
        """
        Start serial communication on specified port.
        
        Args:
            port: Serial port name (e.g., "COM3", "/dev/ttyUSB0")
            baud: Baud rate (e.g., 115200)
        """
        # Stop any existing connection
        self.stop()
        
        # Clear stop flag and start new thread
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop,
            args=(port, baud),
            daemon=False,  # Don't daemon - we want clean shutdown
            name="SerialWorker"
        )
        self._thread.start()

    def stop(self) -> None:
        """
        Stop serial communication and wait for thread to exit.
        
        This method is thread-safe and can be called multiple times.
        """
        if self._thread and self._thread.is_alive():
            self._stop_evt.set()
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                # Thread didn't exit cleanly - this shouldn't happen
                self.rx_q.put("[PC] ⚠ Serial thread failed to stop cleanly\n")

    def send(self, text: str) -> None:
        """
        Queue a command for transmission (non-blocking).
        
        Args:
            text: Command to send (newline will be added)
            
        The command is echoed to rx_q with ">>>" prefix for console display.
        """
        line = text.rstrip()  # Remove any trailing whitespace
        self.rx_q.put(f">>> {line}\n")  # Echo to console
        self.tx_q.put(line + "\n")      # Queue for transmission

    def send_and_wait(self, text: str, timeout: float = DEFAULT_ACK_TIMEOUT) -> bool:
        """
        Send command and wait for acknowledgment (OK/ERR response).
        
        Args:
            text: Command to send
            timeout: Max seconds to wait for response
            
        Returns:
            True if ACK received, False if timeout
            
        This is useful for configuration commands that need confirmation.
        """
        # Clear any stale acknowledgments in the queue
        while not self.ack_q.empty():
            try:
                self.ack_q.get_nowait()
            except queue.Empty:
                break

        # Send the command
        self.send(text)

        # Wait for response with timeout
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
                
            try:
                line = self.ack_q.get(timeout=remaining)
                # Check if this is an acknowledgment
                clean_line = line.strip()
                if clean_line.startswith(("OK", "ERR")):
                    return True  # Got acknowledgment
                # If not an ACK, keep waiting (might be debug output)
            except queue.Empty:
                pass

        # Timeout - log warning
        self.rx_q.put(f"[PC] ✖ No response for: {text.strip()}\n")
        return False

    def send_many(self, commands: List[str], delay: float = 0.10) -> None:
        """
        Send multiple commands with delay between each.
        
        Args:
            commands: List of commands to send
            delay: Seconds to wait between commands
            
        Useful for initialization sequences.
        """
        for cmd in commands:
            self.send(cmd)
            if delay > 0:
                time.sleep(delay)

    @staticmethod
    def ports() -> List[str]:
        """
        Get list of available serial ports.
        
        Returns:
            List of port names, or empty list if PySerial not available
        """
        if serial is None:
            return []
        return [p.device for p in serial.tools.list_ports.comports()]

    def is_connected(self) -> bool:
        """Check if currently connected to serial port."""
        return self._is_connected

    # ────────────────────── Internal Loop ──────────────────────

    def _loop(self, port: str, baud: int) -> None:
        """
        Main worker thread loop.
        
        Handles:
        - Connection/reconnection
        - Reading from serial port
        - Writing queued commands
        - Error recovery
        """
        ser = None
        
        while not self._stop_evt.is_set():
            # ──────── Connection Management ────────
            if ser is None or not ser.is_open:
                self._is_connected = False
                
                # Check if port exists
                if port not in self.ports():
                    time.sleep(self.RETRY_INTERVAL)
                    continue
                
                # Try to connect
                try:
                    ser = serial.Serial(
                        port=port,
                        baudrate=baud,
                        timeout=self.READ_TIMEOUT,  # Non-blocking read
                        write_timeout=1.0,          # Prevent write blocking
                        # Common settings for Arduino/ESP32
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        xonxoff=False,
                        rtscts=False,
                        dsrdtr=False
                    )
                    self._is_connected = True
                    self.rx_q.put(f"[PC] ✓ Connected to {port} @ {baud} baud\n")
                    
                    # Clear any garbage in buffers
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                    
                except Exception as e:
                    self.rx_q.put(f"[PC] ✖ Failed to open {port}: {e}\n")
                    time.sleep(self.RETRY_INTERVAL)
                    continue

            # ──────── Data Transfer ────────
            try:
                # Read all available lines (not just one)
                while ser.in_waiting > 0:
                    # Read line (blocks up to timeout if no newline)
                    raw_line = ser.readline()
                    if raw_line:
                        # Decode with error handling
                        try:
                            line = raw_line.decode('ascii', errors='replace')
                        except UnicodeDecodeError:
                            line = f"[DECODE ERROR: {raw_line.hex()}]\n"
                        
                        # Distribute to queues
                        self.rx_q.put(line)    # For console display
                        self.ack_q.put(line)   # For send_and_wait()
                
                # Send queued commands (process all available)
                tx_count = 0
                while tx_count < 10 and not self.tx_q.empty():
                    try:
                        cmd = self.tx_q.get_nowait()
                        ser.write(cmd.encode('ascii'))
                        ser.flush()  # Force immediate transmission
                        tx_count += 1
                    except queue.Empty:
                        break
                    except serial.SerialTimeoutException:
                        self.rx_q.put("[PC] ⚠ Write timeout - buffer full?\n")
                        break
                
                # Small sleep to prevent CPU spinning
                if ser.in_waiting == 0 and tx_count == 0:
                    time.sleep(0.001)  # 1ms sleep when idle
                    
            except (serial.SerialException, OSError) as e:
                # Connection lost
                self._is_connected = False
                self.rx_q.put(f"[PC] ✖ Connection lost: {e}\n")
                try:
                    ser.close()
                except Exception:
                    pass
                ser = None
                time.sleep(self.RETRY_INTERVAL)

        # ──────── Cleanup ────────
        if ser and ser.is_open:
            try:
                ser.close()
                self.rx_q.put(f"[PC] Closed {port}\n")
            except Exception:
                pass
        
        self._is_connected = False
        self.rx_q.put("[PC] Serial worker stopped\n")