/*********************************************************************
 * vrchat_board.cpp - BrainFlow UDP driver for VRChat EEG Board
 * 
 * This driver interfaces with a custom ESP32-based 16-channel EEG board that uses the ADS1299 chip. 
 * The board communicates via UDP (User Datagram Protocol - a fast network protocol):
 * - Data port (5001): High-speed EEG data streaming
 * - Control port (5000): Configuration commands and keep-alive messages
 * 
 * FEATURES:
 * - Auto-discovery: Automatically finds board IP via beacon packets
 * - Manual IP: Can also specify board IP directly
 * 
 * DATA PACKET FORMAT (52 bytes per frame):
 * +-------------+-------------------------+--------------+
 * | Offset      | Content                 | Size         |
 * +-------------+-------------------------+--------------+
 * | 0-47        | 16 channels x 3 bytes   | 48 bytes     |
 * |             | (24-bit signed samples) |              |
 * | 48-51       | Hardware timestamp      | 4 bytes      |
 * |             | (units: 8 microseconds) |              |
 * +-------------+-------------------------+--------------+
 * 
 * Think of a "frame" as one snapshot of all 16 channels at a single moment in time.
 * 
 * UDP DATAGRAM FORMAT:
 * [ frame_0 | frame_1 | ... | frame_n-1 | battery_voltage(float) ]
 * Total size = n*52 + 4 bytes, where 1 <= n <= 28
 * 
 * The board packs multiple frames into one network packet for efficiency.
 * Why max 28 frames? Ethernet MTU (1500) - IP header (20) - UDP header (8) = 1472 bytes
 * (1472 - 4) / 52 = 28.23, so maximum 28 complete frames per packet
 *********************************************************************/

#include "vrchat_board.h"

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <numeric>
#include <sstream>
#include <mutex>

#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #pragma comment(lib, "ws2_32.lib")
#else
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #include <fcntl.h>
    #include <errno.h>
#endif

#include "brainflow_constants.h"
#include "timestamp.h"


// ====================================================================
//                      PROTOCOL CONSTANTS
// ====================================================================

// ----------- Data Format Constants -----------
constexpr int CHANNELS_PER_BOARD = 16;                                     // Number of EEG channels on the board
constexpr int BYTES_PER_CHANNEL  = 3;                                      // Each sample is 24 bits = 3 bytes
constexpr int CHANNEL_DATA_SIZE  = CHANNELS_PER_BOARD * BYTES_PER_CHANNEL; // Total bytes for all channels (48)
constexpr int TIMESTAMP_SIZE     = 4;                                      // Hardware clock timestamp (32 bits = 4 bytes)
constexpr int FRAME_SIZE         = CHANNEL_DATA_SIZE + TIMESTAMP_SIZE;     // One complete frame (52 bytes)

// ----------- UDP Packet Constants -----------
constexpr int BATTERY_SIZE = 4;                                            // Battery voltage as 32-bit floating point

// Network MTU (Maximum Transmission Unit) explanation:
// Ethernet standard specifies 1500-byte maximum frame payload. Any larger packet gets fragmented
// (split into pieces), which hurts performance and reliability. We must subtract protocol headers:
// - IPv4 header = 20 bytes (source/dest IP, protocol type, checksum, etc.)
// - UDP header = 8 bytes (source/dest port, length, checksum)
// Available for our data = 1500 - 20 - 8 = 1472 bytes
// This is why we pack exactly 28 frames - using full capacity without fragmentation.
constexpr int MAX_UDP_PAYLOAD = 1472;

// Maximum frames that fit in one UDP packet
constexpr int MAX_FRAMES_PER_PACKET = (MAX_UDP_PAYLOAD - BATTERY_SIZE) / FRAME_SIZE;  // 28

// Receive buffer is slightly larger than standard MTU for safety
// 1. Protects against jumbo frames (non-standard large packets up to 9000 bytes on some LANs)
// 2. Some embedded network stacks don't respect MTU perfectly
// 3. Allows for future protocol extensions
// Extra 28 bytes (1500-1472) costs nothing but prevents buffer overrun
constexpr int RECV_BUFFER_SIZE = 1500;

// ----------- Timing Constants -----------
constexpr int KEEPALIVE_INTERVAL_SEC    = 5;                              // Board timeout prevention
constexpr int DEFAULT_DISCOVERY_TIMEOUT_MS = 3000;                        // Board beacon wait time
constexpr int CONTROL_SOCKET_TIMEOUT_MS = 1000;                           // Command response timeout

// ----------- Network Port Defaults -----------
constexpr int DEFAULT_DATA_PORT    = 5001;                                // High-speed EEG data
constexpr int DEFAULT_CONTROL_PORT = 5000;                                // Commands and beacons

// ----------- ADS1299 Scaling -----------
// The ADS1299 is the chip that measures brain signals. It converts analog voltages to digital numbers.
// Per ADS1299 datasheet: input range is +/-4.5V (4.5V comes from the chip's reference voltage specification).
// With 24-bit signed resolution: positive range uses 2^23 steps, negative range uses 2^23 steps.
// Each LSB (Least Significant Bit) represents: 4.5V / 2^23 = 0.536 microvolts
// This scale factor converts raw ADC counts to actual voltage.
constexpr double ADS1299_SCALE = 4.5 / double(1 << 23);


// ====================================================================
//                        CONSTRUCTOR / DESTRUCTOR
// ====================================================================

VrchatBoard::VrchatBoard (int board_id, struct BrainFlowInputParams params)
    : Board (board_id, params),  // Call parent Board constructor
      data_port_ (params.ip_port     ? params.ip_port     : DEFAULT_DATA_PORT),
      ctrl_port_ (params.ip_port_aux ? params.ip_port_aux : DEFAULT_CONTROL_PORT)
{
    // Constructor body is empty because all initialization happens in the initializer list above.
    // This is more efficient (avoids default construction followed by assignment) and is required
    // for const members, references, and base class initialization. Also ensures exception safety.
}

VrchatBoard::~VrchatBoard ()
{
    // Always call release_session to ensure cleanup. Safe to call even if prepare_session was never called
    // or failed, because release_session checks initialized_ flag and all cleanup functions handle nullptr/-1.
    release_session ();
}

// ====================================================================
//                         SESSION MANAGEMENT
// ====================================================================

int VrchatBoard::prepare_session ()
{
    // Don't reinitialize if already prepared
    if (initialized_)
    {
        safe_logger (spdlog::level::info, "Session already prepared");
        return (int)BrainFlowExitCodes::STATUS_OK;
    }

    // ----------- Create Data Socket (for receiving EEG data) -----------
    // This socket RECEIVES high-speed UDP packets from the board. We "bind" it to a specific port number,
    // which is like telling the operating system "any data arriving on port 5001 should come to me".
    data_srv_ = new SocketServerUDP (data_port_);
    
    // Attempt to bind the data socket
    int bind_result = data_srv_->bind ();
    if (bind_result != (int)SocketServerUDPReturnCodes::STATUS_OK)
    {
        safe_logger (spdlog::level::err, "Failed to bind data port {} - port may be in use", data_port_);
        delete data_srv_;
        data_srv_ = nullptr;
        return (int)BrainFlowExitCodes::UNABLE_TO_OPEN_PORT_ERROR;
    }

    // ----------- Handle Board IP Discovery or Direct Connection -----------
    // If no IP provided, use auto-discovery via beacon. If IP provided, connect directly.
    
    std::string board_ip = params.ip_address;
    
    if (board_ip.empty ())
    {
        // Wait for board beacon (configurable timeout)
        int timeout_ms = DEFAULT_DISCOVERY_TIMEOUT_MS;
        
        // Check if custom timeout specified in other_info
        size_t timeout_pos = params.other_info.find("discovery_timeout=");
        if (timeout_pos != std::string::npos)
        {
            try
            {
                timeout_ms = std::stoi(params.other_info.substr(timeout_pos + 18));
            }
            catch (...)
            {
                // Keep default timeout if parsing fails (e.g., "discovery_timeout=abc" or overflow).
                // This ensures discovery still works even with malformed config strings.
            }
        }
        
        bool discovered = wait_for_beacon (timeout_ms);
        
        if (!discovered)
        {
            safe_logger (spdlog::level::err, "Failed to discover board - no beacon received within {}ms", timeout_ms);
            
            // Cleanup
            data_srv_->close ();
            delete data_srv_;
            data_srv_ = nullptr;
            
            return (int)BrainFlowExitCodes::BOARD_NOT_READY_ERROR;
        }
        
        board_ip = discovered_ip_;
        safe_logger (spdlog::level::info, "Board discovered at IP: {}", board_ip);
    }

    // ----------- Create Control Socket (for sending/receiving commands) -----------
    // We use raw UDP socket instead of SocketServerUDP because we need sendto() functionality
    // to send commands to specific IP addresses (board IP). SocketServerUDP is receive-only.
    
    // Initialize platform-specific socket support if needed
#ifdef _WIN32
    if (!wsa_initialized_)
    {
        WSADATA wsaData;
        if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0)
        {
            safe_logger (spdlog::level::err, "Failed to initialize Winsock");
            data_srv_->close ();
            delete data_srv_;
            data_srv_ = nullptr;
            return (int)BrainFlowExitCodes::GENERAL_ERROR;
        }
        wsa_initialized_ = true;
    }
#endif
    
    // Create raw UDP socket for control
    ctrl_socket_ = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (ctrl_socket_ < 0)
    {
        safe_logger (spdlog::level::err, "Failed to create control socket");
        data_srv_->close ();
        delete data_srv_;
        data_srv_ = nullptr;
        return (int)BrainFlowExitCodes::GENERAL_ERROR;
    }
    
    // Allow port reuse - this lets us quickly restart the program without waiting for the OS to release the port.
    // Without this, you might get "port already in use" errors when restarting quickly.
    int reuse = 1;
    if (setsockopt(ctrl_socket_, SOL_SOCKET, SO_REUSEADDR, 
                   (const char*)&reuse, sizeof(reuse)) < 0)
    {
        // Non-critical error - program will still work. Port reuse just improves developer experience
        // during testing/debugging. Worst case: might need to wait 30-60 seconds between restarts.
    }
    
    // Bind to control port
    struct sockaddr_in bind_addr;
    memset(&bind_addr, 0, sizeof(bind_addr));  // Zero-initialize to prevent undefined behavior  // Zero all fields to ensure no garbage in padding
    bind_addr.sin_family = AF_INET;
    bind_addr.sin_addr.s_addr = INADDR_ANY;  // Accept packets on any network interface
                                              // (important for multi-homed systems with WiFi + Ethernet)
    bind_addr.sin_port = htons(ctrl_port_);  // htons = host to network short (byte order conversion)
    
    if (bind(ctrl_socket_, (struct sockaddr*)&bind_addr, sizeof(bind_addr)) < 0)
    {
        safe_logger (spdlog::level::err, "Failed to bind control socket on port {}", ctrl_port_);
#ifdef _WIN32
        closesocket(ctrl_socket_);
#else
        close(ctrl_socket_);
#endif
        ctrl_socket_ = -1;
        data_srv_->close ();
        delete data_srv_;
        data_srv_ = nullptr;
        return (int)BrainFlowExitCodes::UNABLE_TO_OPEN_PORT_ERROR;
    }
    
    // Set socket timeout
#ifdef _WIN32
    DWORD timeout = CONTROL_SOCKET_TIMEOUT_MS;  // milliseconds
    setsockopt(ctrl_socket_, SOL_SOCKET, SO_RCVTIMEO, (const char*)&timeout, sizeof(timeout));
#else
    struct timeval tv;
    tv.tv_sec = CONTROL_SOCKET_TIMEOUT_MS / 1000;
    tv.tv_usec = (CONTROL_SOCKET_TIMEOUT_MS % 1000) * 1000;  // Convert remaining milliseconds to microseconds
                                                              // e.g., 1500ms = 1 sec + 500ms; 500ms * 1000 = 500000 microsec
    setsockopt(ctrl_socket_, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
#endif
    
    // Store the board IP for sending commands
    board_ip_ = board_ip;

    // Mark session as initialized
    initialized_ = true;
    safe_logger (spdlog::level::info, "Session prepared successfully");
    
    return (int)BrainFlowExitCodes::STATUS_OK;
}

int VrchatBoard::prepare_session_with_discovery (int timeout_ms)
{
    /*
     * Convenience method for explicit discovery with custom timeout.
     * 
     * @param timeout_ms Maximum time to wait for board discovery
     * @return BrainFlowExitCodes::STATUS_OK on success
     * 
     * Usage: board.prepare_session_with_discovery(5000);  // Wait up to 5 seconds
     */
    
    // Temporarily clear IP to force discovery
    std::string saved_ip = params.ip_address;
    params.ip_address = "";
    
    // Add timeout to other_info
    std::string saved_other = params.other_info;
    params.other_info += " discovery_timeout=" + std::to_string(timeout_ms);
    
    // Attempt discovery
    int result = prepare_session();
    
    // Restore original params
    params.ip_address = saved_ip;
    params.other_info = saved_other;
    
    return result;
}

std::string VrchatBoard::get_discovered_ip () const
{
    /*
     * Get the discovered board IP address.
     * 
     * @return Board IP if discovered, empty string otherwise
     */
    return discovered_ip_;
}

int VrchatBoard::start_stream (int buffer_size, const char *streamer_params)
{
    // Validate preconditions
    if (!initialized_)
    {
        safe_logger (spdlog::level::err, "Session not prepared - call prepare_session() first");
        return (int)BrainFlowExitCodes::BOARD_NOT_CREATED_ERROR;
    }
    
    if (streaming_)
    {
        safe_logger (spdlog::level::err, "Stream already running");
        return (int)BrainFlowExitCodes::STREAM_ALREADY_RUN_ERROR;
    }
    
    // Initialize BrainFlow's internal buffers and streamers
    int result = prepare_for_acquisition (buffer_size, streamer_params);
    if (result != (int)BrainFlowExitCodes::STATUS_OK)
    {
        safe_logger (spdlog::level::err, "Failed to prepare acquisition: {}", result);
        return result;
    }

    // Set thread control flag and launch worker threads
    keep_alive_ = true;
    
    // Launch data reception thread - this receives and processes EEG packets
    read_th_ = std::thread (&VrchatBoard::read_thread, this);
    
    // Launch keep-alive thread - this sends periodic "floof" messages
    ping_th_ = std::thread (&VrchatBoard::ping_thread, this);
    
    // Mark streaming as active
    streaming_ = true;

    safe_logger (spdlog::level::info, "Stream started successfully");
    
    return (int)BrainFlowExitCodes::STATUS_OK;
}


int VrchatBoard::stop_stream ()
{
    if (!streaming_)
    {
        safe_logger (spdlog::level::warn, "Stream not running");
        return (int)BrainFlowExitCodes::STREAM_THREAD_IS_NOT_RUNNING;
    }
    
    // Signal threads to stop
    keep_alive_ = false;
    
    // Wait for threads to finish
    // joinable() check prevents exception if thread was never started (e.g., start_stream failed early)
    // Note: read thread may take up to SocketServerUDP's internal timeout to notice keep_alive_ change
    if (read_th_.joinable ())
    {
        read_th_.join ();
    }
    
    if (ping_th_.joinable ())
    {
        ping_th_.join ();
    }
    
    // Clear streaming flag
    streaming_ = false;
    
    safe_logger (spdlog::level::info, "Stream stopped successfully");
    
    return (int)BrainFlowExitCodes::STATUS_OK;
}


int VrchatBoard::release_session ()
{
    // Stop streaming if active
    if (streaming_)
    {
        stop_stream ();
    }
    
    // Close all sockets and free resources
    close_sockets ();
    
    // Clear initialization flag
    initialized_ = false;
    
    // Clear discovered IP
    discovered_ip_.clear();
    board_ip_.clear();
    
    // Reset timestamp alignment
    first_packet_received_ = false;
    timestamp_offset_ = 0.0;
    
    safe_logger (spdlog::level::info, "Session released");
    
    return (int)BrainFlowExitCodes::STATUS_OK;
}

// ====================================================================
//                      BOARD CONFIGURATION
// ====================================================================

int VrchatBoard::config_board (std::string config, std::string &response)
{
    /*
     * This method sends configuration commands to the board via UDP.
     * 
     * SUPPORTED COMMANDS:
     * -----------------------------------------------------------------
     * Filter Control (filters clean up the EEG signal):
     *   - "sys filters_on"               : Enable all filters
     *   - "sys filters_off"              : Disable all filters
     *   - "sys filter_equalizer_on/off"  : Toggle equalizer filter (balances frequencies)
     *   - "sys filter_dc_on/off"         : Toggle DC blocking filter (removes constant offset)
     *   - "sys filter_5060_on/off"       : Toggle 50/60Hz notch filter (removes power line noise)
     *   - "sys filter_100120_on/off"     : Toggle 100/120Hz notch filter (removes harmonics)
     * 
     * Settings:
     *   - "sys networkfreq [50|60]"      : Set your country's power line frequency (50Hz Europe/Asia, 60Hz Americas)
     *   - "sys dccutofffreq [0.5|1|2|4|8]" : Set DC filter cutoff frequency in Hz (lower = slower drift removal)
     *   - "sys digitalgain [1-256]"      : Set amplification factor (higher = bigger signal, but may clip)
     * 
     * Board Management:
     *   - "sys esp_reboot"               : Reboot the ESP32 microcontroller
     *   - "sys adc_reset"                : Reset the ADS1299 ADC chip (analog-to-digital converter)
     *   - "sys erase_flash"              : Erase saved WiFi credentials
     *   - "sys start_cnt"                : Start continuous data transmission mode
     *   - "sys stop_cnt"                 : Stop continuous data transmission mode
     * -----------------------------------------------------------------
     */

    // Validate that we have a control socket
    if (ctrl_socket_ < 0)
    {
        safe_logger (spdlog::level::err, 
            "Control socket not available - board IP must be provided or discovered");
        response = "NO_CONTROL_SOCKET";
        return (int)BrainFlowExitCodes::BOARD_NOT_READY_ERROR;
    }

    // Validate input
    if (config.empty())
    {
        safe_logger (spdlog::level::err, "Empty configuration string provided");
        response = "EMPTY_CONFIG";
        return (int)BrainFlowExitCodes::INVALID_ARGUMENTS_ERROR;
    }

    // Validate that we have a board IP
    if (board_ip_.empty())
    {
        safe_logger (spdlog::level::err, "No board IP - discovery required");
        response = "NO_BOARD_IP";
        return (int)BrainFlowExitCodes::BOARD_NOT_READY_ERROR;
    }

    // ----------- Send Command via UDP -----------
    // Protect control socket with mutex. Without this lock, ping_thread could send "floof" while
    // we're waiting for a command response, causing us to receive "floof" response instead of
    // the actual command result. The mutex ensures operations complete atomically.
    std::lock_guard<std::mutex> lock(ctrl_mutex_);
    
    // Prepare destination address for the board's control port
    struct sockaddr_in dest_addr;
    memset(&dest_addr, 0, sizeof(dest_addr));  // Zero all fields to prevent garbage values in padding bytes
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(ctrl_port_);
    inet_pton(AF_INET, board_ip_.c_str(), &dest_addr.sin_addr);  // Convert IP string to binary format
    
    // Send command
    int bytes_sent = sendto(ctrl_socket_, config.c_str(), config.length(), 0,
                           (struct sockaddr*)&dest_addr, sizeof(dest_addr));
    
    if (bytes_sent < 0)
    {
        safe_logger (spdlog::level::err, 
            "Failed to send command '{}' - sendto() returned: {}", config, bytes_sent);
        response = "SEND_FAILED";
        return (int)BrainFlowExitCodes::BOARD_WRITE_ERROR;
    }

    // ----------- Wait for Response (with timeout) -----------
    // Some commands may not send a response, so timeout is not an error condition for this protocol.
    char buffer[256] = {0};  // Response buffer - board responses are typically < 50 bytes
    
    // Attempt to receive response
    int bytes_received = recv(ctrl_socket_, buffer, sizeof(buffer) - 1, 0);
    
    if (bytes_received > 0)
    {
        // Ensure null termination for string safety before using the buffer as a C string
        buffer[bytes_received] = '\0';
        response = std::string(buffer);
        
        // Check if board reported an error. Board firmware prefixes error responses with "ERR"
        // (e.g., "ERR: Invalid command" or "ERR: Parameter out of range")
        if (response.find("ERR") != std::string::npos)
        {
            safe_logger (spdlog::level::err, 
                "Board returned error for command '{}': {}", config, response);
            return (int)BrainFlowExitCodes::BOARD_WRITE_ERROR;
        }
        
        // Command executed successfully
        return (int)BrainFlowExitCodes::STATUS_OK;
    }
    else if (bytes_received == 0)
    {
        // Connection closed
        safe_logger (spdlog::level::err, 
            "Connection closed while waiting for response to '{}'", config);
        response = "CONNECTION_CLOSED";
        
        return (int)BrainFlowExitCodes::BOARD_WRITE_ERROR;
    }
    else
    {
        // Check if it's a timeout (which is normal for some commands)
#ifdef _WIN32
        int error = WSAGetLastError();
        if (error == WSAETIMEDOUT || error == WSAEWOULDBLOCK)
        {
            // Timeout is expected for some commands. Board firmware has three response patterns:
            // 1. Immediate response with result (e.g., "OK: filters_on")
            // 2. No response by design (e.g., "sys adc_reset" just executes)
            // 3. Delayed response (rare, for slow operations)
            // We treat timeout as success to handle case #2.
            response = "TIMEOUT";
            
            return (int)BrainFlowExitCodes::STATUS_OK;
        }
        else
        {
            // Real socket error
            safe_logger (spdlog::level::err, 
                "Socket recv error for command '{}': {} (WSA error: {})", config, bytes_received, error);
            response = "RECV_ERROR";
            return (int)BrainFlowExitCodes::BOARD_WRITE_ERROR;
        }
#else
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == ETIMEDOUT)
        {
            // Timeout is expected for some commands. Board firmware has three response patterns:
            // 1. Immediate response with result (e.g., "OK: filters_on")
            // 2. No response by design (e.g., "sys adc_reset" just executes)
            // 3. Delayed response (rare, for slow operations)
            // We treat timeout as success to handle case #2.
            response = "TIMEOUT";
            
            return (int)BrainFlowExitCodes::STATUS_OK;
        }
        else
        {
            // Real socket error
            safe_logger (spdlog::level::err, 
                "Socket recv error for command '{}': {} (errno: {})", config, bytes_received, errno);
            response = "RECV_ERROR";
            return (int)BrainFlowExitCodes::BOARD_WRITE_ERROR;
        }
#endif
    }
}

// ====================================================================
//                    DATA RECEPTION THREAD
// ====================================================================

void VrchatBoard::read_thread ()
{
    // ----------- BrainFlow Channel Mapping -----------
    // Get board description to know which BrainFlow channels to use
    // Default channel layout:
    //   0-15: EEG channels (16 channels)
    //   16:   Battery voltage
    //   17:   Hardware timestamp (from board's internal clock)
    //   18:   Marker channel (for events)
    //   19:   Other/Reserved
    //   20:   Other/Reserved
    
    int num_rows = 0;                   // Total number of channels in BrainFlow
    std::vector<int> eeg_idx (CHANNELS_PER_BOARD);      // Indices for EEG channels
    int battery_idx = -1;               // Initialize to -1 (invalid) to detect if config explicitly sets it. 
                                        // Prevents accidental writes if channel not configured.
    int hw_timestamp_idx = -1;          // Initialize to -1 (invalid) for same reason - ensures we only write
                                        // to this channel if explicitly configured in board description.

    try
    {
        if (!board_descr.empty ())  // board_descr is JSON from BrainFlow's board registry
        {
            // Get channel mapping from board description JSON
            num_rows = board_descr["default"]["num_rows"];
            eeg_idx = board_descr["default"]["eeg_channels"].get<std::vector<int>>();
            
            // Get battery channel if defined
            if (board_descr["default"].contains("battery_channel"))
            {
                battery_idx = board_descr["default"]["battery_channel"];
            }

            // Get timestamp channel if defined
            if (board_descr["default"].contains("timestamp_channel"))
            {
                hw_timestamp_idx = board_descr["default"]["timestamp_channel"];
            }
        }
    }
    catch (...)
    {
        safe_logger (spdlog::level::warn, "Failed to parse board description");
    }

    // Fallback if board description is missing
    if (num_rows == 0)
    {
        num_rows = 21;  // 16 EEG + battery + hw_timestamp + marker + 2 other/reserved
        std::iota (eeg_idx.begin (), eeg_idx.end (), 0);  // Fill with 0,1,2,...15 (sequential channel numbers)
        battery_idx = 16;      // Battery voltage channel
        hw_timestamp_idx = 17; // Hardware timestamp channel
        safe_logger (spdlog::level::warn, 
            "Board description missing - using default {} rows", num_rows);
    }
    
    // ----------- Buffers for Data Reception -----------
    std::vector<double> package (num_rows, 0.0);    // BrainFlow data package. Pre-filled with zeros to ensure
                                                     // unused channels (markers, reserved) have defined values.
    std::vector<uint8_t> recv_buffer (RECV_BUFFER_SIZE);    // UDP receive buffer

    // Statistics counters for debugging/monitoring. Not exposed via BrainFlow API currently,
    // but could be logged or made available through config_board() if needed for diagnostics.
    unsigned long datagram_count = 0;     // Total UDP packets received
    unsigned long frame_count = 0;        // Total EEG frames processed  
    unsigned long bad_packet_count = 0;   // Packets with wrong size/format

    // ----------- Main Reception Loop -----------
    while (keep_alive_)
    {
        // Receive UDP datagram (blocking with timeout)
        int bytes_received = data_srv_->recv (recv_buffer.data (), static_cast<int>(recv_buffer.size ()));
        
        if (bytes_received <= 0)
        {
            // No data received - either timeout or error. Both are normal:
            // - Timeout: SocketServerUDP has internal timeout (varies by platform, typically 100-1000ms)
            //   This allows thread to periodically check keep_alive_ flag and exit cleanly
            // - Error: Network temporarily unavailable, will retry on next loop iteration
            continue;
        }

        // Get PC timestamp when packet is received (UNIX microseconds)
        double pc_timestamp = get_timestamp();

        // ----------- Validate Packet Size -----------
        // Valid packet must be: n*FRAME_SIZE + BATTERY_SIZE bytes (n frames + battery)
        if (bytes_received < FRAME_SIZE + BATTERY_SIZE)
        {
            // Packet too small
            ++bad_packet_count;
            safe_logger (spdlog::level::warn, 
                "Packet too small: {} bytes (minimum: {})", bytes_received, FRAME_SIZE + BATTERY_SIZE);
            continue;
        }
        
        if ((bytes_received - BATTERY_SIZE) % FRAME_SIZE != 0)
        {
            // Packet size doesn't match expected format
            ++bad_packet_count;
            safe_logger (spdlog::level::warn, 
                "Invalid packet size: {} bytes (not n*{} + {})", bytes_received, FRAME_SIZE, BATTERY_SIZE);
            continue;
        }

        // Calculate number of frames in this packet
        const int frames_in_packet = (bytes_received - BATTERY_SIZE) / FRAME_SIZE;
        ++datagram_count;

        // ----------- Extract Battery Voltage -----------
        // Last BATTERY_SIZE bytes contain battery voltage as IEEE 754 32-bit float in little-endian format.
        // Little-endian = least significant byte first. Example: float 12.5 = 0x41480000 in hex,
        // stored as bytes: [0x00, 0x00, 0x48, 0x41]. This is ESP32/Arduino default byte order.
        // memcpy handles endianness correctly on all platforms.
        float battery_voltage;
        memcpy(&battery_voltage, &recv_buffer[bytes_received - BATTERY_SIZE], sizeof(float));

        // ----------- Process Each Frame in Packet -----------
        for (int frame_idx = 0; frame_idx < frames_in_packet; ++frame_idx)
        {
            // Calculate offset to current frame
            const uint8_t *frame_data = recv_buffer.data () + (frame_idx * FRAME_SIZE);

            // ----------- Parse 24-bit Samples -----------
            // Each channel uses 3 bytes to represent one sample value. The bytes are arranged in big-endian format,
            // meaning the most significant byte (MSB - the byte with the largest value contribution) comes first.
            for (size_t ch = 0; ch < eeg_idx.size (); ++ch)
            {
                // Extract 3 bytes for this channel
                const int byte_offset = ch * BYTES_PER_CHANNEL;
                
                // Combine 3 bytes into 24-bit unsigned value. Big-endian byte order means:
                // byte[0] = MSB (most significant), byte[2] = LSB (least significant)
                // Example: bytes [0x12, 0x34, 0x56] become 0x123456 = 1,193,046 decimal
                uint32_t raw_24bit = (frame_data[byte_offset]     << 16) |  // MSB shifted to bits 23-16
                                     (frame_data[byte_offset + 1] << 8)  |  // Middle byte to bits 15-8
                                      frame_data[byte_offset + 2];          // LSB stays in bits 7-0
                
                // Sign-extension: Convert 24-bit signed to 32-bit signed while preserving sign.
                // This works by shifting left 8 bits (putting the 24-bit value in the upper bits of a 32-bit int),
                // then arithmetic right shift 8 bits (which replicates the sign bit). Branchless technique
                // avoids if-statements, improving performance by preventing CPU pipeline stalls.
                int32_t raw_value = (int32_t)(raw_24bit << 8) >> 8;
                
                // Convert the raw ADC value to actual voltage and store in BrainFlow's data package
                package[eeg_idx[ch]] = raw_value * ADS1299_SCALE;
            }

            // ----------- Extract Hardware Timestamp -----------
            // Bytes 48-51 contain a 32-bit unsigned integer timestamp from the board's internal clock.
            // Format: little-endian, units of 8 microseconds since board power-on.
            // We store this to detect packet loss (gaps > expected interval) and measure timing jitter.
            if ((hw_timestamp_idx >= 0) && (hw_timestamp_idx < num_rows))
            {
                uint32_t hw_timestamp;
                memcpy(&hw_timestamp, &frame_data[48], sizeof(uint32_t));
                // Convert to seconds: multiply by 8 microseconds per tick
                double hw_time_seconds = hw_timestamp * 8.0;
                
                // On first packet, calculate offset to align hardware time with PC time
                if (!first_packet_received_)
                {
                    timestamp_offset_ = pc_timestamp - hw_time_seconds;
                    first_packet_received_ = true;
                    safe_logger (spdlog::level::debug, 
                        "Timestamp alignment: PC={:.6f}, HW={:.6f}, Offset={:.6f}", 
                        pc_timestamp, hw_time_seconds, timestamp_offset_);
                }
                
                // Apply offset to convert hardware time to PC time
                package[hw_timestamp_idx] = hw_time_seconds + timestamp_offset_;
            }

            // ----------- Add Battery Voltage -----------
            // Store battery voltage in configured channel. The bounds check prevents writing
            // past array end if board description specifies invalid channel number.
            if ((battery_idx >= 0) && (battery_idx < num_rows))
            {
                package[battery_idx] = battery_voltage;
            }

            // ----------- Send to BrainFlow -----------
            // Push the complete data package to BrainFlow's ring buffer. This makes the data available
            // to the user's application via get_board_data() or similar BrainFlow API calls.
            // Channels 18, 19, 20 remain as zeros (initialized at buffer creation) - reserved for user
            // markers and future features. Users can write to marker channel via BrainFlow API.
            push_package (package.data (), (int)BrainFlowPresets::DEFAULT_PRESET);
            ++frame_count;
        }
    }
}

// ====================================================================
//                    KEEP-ALIVE THREAD (FLOOF)
// ====================================================================

void VrchatBoard::ping_thread ()
{
    /*
     * This thread sends periodic "floof" messages to the board.
     * 
     * PURPOSE:
     * - Maintains UDP connection state (keeps the connection "alive")
     * - Prevents board timeout - board firmware stops sending data if no messages received for 100 seconds
     * - Helps with NAT traversal - home routers/firewalls close inactive UDP mappings after 30-300 seconds,
     *   our 5-second interval ensures the path stays open
     * 
     * The word "floof" is an arbitrary keep-alive message that the board recognizes.
     * Any message would work, but "floof" is short and unlikely to conflict with commands.
     */

    using namespace std::chrono_literals;  // Enables 5s syntax instead of std::chrono::seconds(5)
    unsigned long floof_count = 0;  // Track successful keep-alives for debugging connection stability

    // Send keep-alive every KEEPALIVE_INTERVAL_SEC seconds
    while (keep_alive_)
    {
        if (ctrl_socket_ >= 0 && !board_ip_.empty())  // Only send if socket is open AND we know where to send
        {
            // Protect control socket with mutex. This prevents config_board() from interfering
            // with our keep-alive messages. Without this lock, responses could get mixed up.
            std::lock_guard<std::mutex> lock(ctrl_mutex_);
            
            // Prepare destination address
            struct sockaddr_in dest_addr;
            memset(&dest_addr, 0, sizeof(dest_addr));  // Zero-initialize structure
            dest_addr.sin_family = AF_INET;
            dest_addr.sin_port = htons(ctrl_port_);
            inet_pton(AF_INET, board_ip_.c_str(), &dest_addr.sin_addr);  // Board IP was set during prepare_session
            
            // Send the keep-alive message
            int result = sendto(ctrl_socket_, "floof", 5, 0,
                               (struct sockaddr*)&dest_addr, sizeof(dest_addr));
            
            if (result > 0)
            {
                ++floof_count;
            }
            else
            {
                safe_logger (spdlog::level::warn, 
                    "Failed to send keep-alive #{}: {}", floof_count + 1, result);
            }
        }
        
        // Wait before next keep-alive
        std::this_thread::sleep_for (std::chrono::seconds(KEEPALIVE_INTERVAL_SEC));
    }
}


// ====================================================================
//                        HELPER FUNCTIONS
// ====================================================================

bool VrchatBoard::wait_for_beacon (int timeout_ms)
{
    /*
     * Wait for a beacon packet from the board to discover its IP address. The board periodically sends UDP packets 
     * to the control port. This implementation uses raw sockets to extract the sender's IP, then switches back to 
     * BrainFlow's socket classes for normal operation.
     * 
     * Note: This function handles its own Windows socket initialization if needed.
     * 
     * @param timeout_ms Maximum time to wait in milliseconds
     * @return true if board discovered, false if timeout
     */
    
#ifdef _WIN32
    // Initialize Windows sockets if not already done
    if (!wsa_initialized_)
    {
        WSADATA wsaData;
        if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0)
        {
            safe_logger (spdlog::level::err, "Failed to initialize Windows sockets");
            return false;
        }
        wsa_initialized_ = true;
    }
#endif
    
    // Create raw UDP socket for discovery
    int discovery_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (discovery_sock < 0)
    {
        safe_logger (spdlog::level::err, "Failed to create discovery socket");
        return false;
    }
    
    // Allow port reuse
    int reuse = 1;
    if (setsockopt(discovery_sock, SOL_SOCKET, SO_REUSEADDR, 
                   (const char*)&reuse, sizeof(reuse)) < 0)
    {
        // Non-critical error, continue
    }
    
    // Bind to control port
    struct sockaddr_in bind_addr;
    memset(&bind_addr, 0, sizeof(bind_addr));
    bind_addr.sin_family = AF_INET;
    bind_addr.sin_addr.s_addr = INADDR_ANY;  // Listen on all interfaces to catch beacon from any network
    bind_addr.sin_port = htons(ctrl_port_);  // Must match port where board sends beacons
    
    if (bind(discovery_sock, (struct sockaddr*)&bind_addr, sizeof(bind_addr)) < 0)
    {
        safe_logger (spdlog::level::err, "Failed to bind discovery socket on port {}", ctrl_port_);
#ifdef _WIN32
        closesocket(discovery_sock);
#else
        close(discovery_sock);
#endif
        return false;
    }
    
    // Set socket to non-blocking mode for timeout handling. In blocking mode, recvfrom() would wait forever
    // if no data arrives. Non-blocking mode makes it return immediately with EAGAIN/EWOULDBLOCK if no data
    // is ready, allowing us to check elapsed time and exit cleanly on timeout.
#ifdef _WIN32
    u_long nonblocking = 1;
    ioctlsocket(discovery_sock, FIONBIO, &nonblocking);
#else
    int flags = fcntl(discovery_sock, F_GETFL, 0);
    fcntl(discovery_sock, F_SETFL, flags | O_NONBLOCK);
#endif
    
    // Wait for beacon with timeout
    auto start_time = std::chrono::steady_clock::now();
    char buffer[256];  // Beacon messages are typically short (~20 bytes), 256 is generous
    bool discovered = false;
    
    while (!discovered)
    {
        // Check timeout
        auto now = std::chrono::steady_clock::now();
        auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - start_time).count();
        
        if (elapsed_ms >= timeout_ms)
        {
            break;
        }
        
        // Try to receive a packet
        struct sockaddr_in sender_addr;
        socklen_t sender_len = sizeof(sender_addr);
        
        int bytes_received = recvfrom(discovery_sock, buffer, static_cast<int>(sizeof(buffer) - 1),
                                     0, (struct sockaddr*)&sender_addr, &sender_len);
        
        if (bytes_received > 0)
        {
            // Got a packet! Extract sender's IP address from the socket address structure.
            // sockaddr_in contains IP as 32-bit integer; inet_ntop converts to dotted decimal
            // string format (e.g., 0xC0A80164 -> "192.168.1.100")
            char ip_str[INET_ADDRSTRLEN];
            inet_ntop(AF_INET, &sender_addr.sin_addr, ip_str, INET_ADDRSTRLEN);
            
            discovered_ip_ = std::string(ip_str);
            discovered = true;
            
            // Null terminate beacon content for safety if we want to log it. The beacon typically contains
            // a board ID string like "VRChatEEG-v1.0". Without null termination, string functions could
            // read past buffer end. Currently we don't use the content, but this makes it safe if we do.
            buffer[bytes_received] = '\0';
            
            safe_logger (spdlog::level::info, "Board discovered at {}", discovered_ip_);
        }
        else
        {
            // No data available - sleep briefly to avoid busy-waiting (consuming 100% CPU).
            // 10ms is a good balance: responsive enough to catch beacons quickly (beacon sent every ~100ms)
            // but not so frequent that we waste CPU. At 10ms sleep, we check 100 times per second.
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    }
    
    // Cleanup
#ifdef _WIN32
    closesocket(discovery_sock);
#else
    close(discovery_sock);
#endif
    
    return discovered;
}


void VrchatBoard::close_sockets ()
{
    /*
     * Safely close and delete all socket objects. Called during session cleanup to ensure
     * all network resources are properly released. All operations are safe on uninitialized
     * objects: delete nullptr is no-op, close(-1) returns error but doesn't crash.
     */
    
    // Close data reception socket
    if (data_srv_) 
    { 
        data_srv_->close (); 
        delete data_srv_; 
        data_srv_ = nullptr;
    }
    
    // Close control socket
    if (ctrl_socket_ >= 0) 
    { 
#ifdef _WIN32
        closesocket(ctrl_socket_);
#else
        close(ctrl_socket_);
#endif
        ctrl_socket_ = -1;
    }
    
    // Clean up Windows sockets once at the end
#ifdef _WIN32
    if (wsa_initialized_)
    {
        WSACleanup();  // Must match every WSAStartup call. Since we track initialization
                       // with wsa_initialized_, we ensure exactly one cleanup per startup.
        wsa_initialized_ = false;
    }
#endif
}