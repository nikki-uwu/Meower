#pragma once
/*********************************************************************
 * vrchat_board.h - BrainFlow UDP driver for VRChat EEG Board
 * 
 * OVERVIEW:
 * This class implements BrainFlow support for a custom 16-channel EEG board based on ESP32 + ADS1299. 
 * The board communicates via UDP (a fast network protocol that doesn't guarantee delivery):
 * 
 * - Data Port (default 5001): Receives high-speed EEG data packets
 * - Control Port (default 5000): Sends configuration commands to board
 * 
 * FEATURES:
 * - Auto-discovery: Automatically finds board IP via beacon packets (like a lighthouse broadcasting its location)
 * - Manual mode: Can specify board IP directly if you know it
 * - Configuration: Full control over board settings via config_board()
 * 
 * AUTO-DISCOVERY:
 * If no IP address is provided, the board will listen for UDP beacons on the control port and automatically 
 * discover the board's IP address.
 * 
 * USAGE WITH AUTO-DISCOVERY:
 * ```cpp
 * BrainFlowInputParams params;
 * // params.ip_address = "";       // Leave empty for auto-discovery
 * params.ip_port = 5001;           // Data port
 * params.ip_port_aux = 5000;       // Control port
 * 
 * VrchatBoard board(BoardIds::VRCHAT_BOARD, params);
 * board.prepare_session();  // Will auto-discover board
 * board.start_stream();
 * // ... collect data ...
 * board.stop_stream();
 * board.release_session();
 * ```
 * 
 * USAGE WITH DIRECT IP:
 * ```cpp
 * BrainFlowInputParams params;
 * params.ip_address = "192.168.1.100";  // Board IP
 * params.ip_port = 5001;                // Data port
 * params.ip_port_aux = 5000;            // Control port
 * 
 * VrchatBoard board(BoardIds::VRCHAT_BOARD, params);
 * board.prepare_session();
 * board.start_stream();
 * // ... collect data ...
 * board.stop_stream();
 * board.release_session();
 * ```
 *********************************************************************/

#include <atomic>
#include <thread>
#include <vector>
#include <string>
#include <mutex>

#include "board.h"
#include "board_controller.h"
#include "socket_server_udp.h"


class VrchatBoard : public Board
{
public:
    // ====================================================================
    //                      PUBLIC INTERFACE
    // ====================================================================
    
    /**
     * Constructor - initializes board with connection parameters
     * @param board_id Board type identifier from BoardIds enum
     * @param params Connection parameters (IP, ports, etc.)
     * 
     * Special params.other_info options:
     * - "discovery_timeout=5000" : Set discovery timeout in ms (default 3000)
     */
    VrchatBoard (int board_id, struct BrainFlowInputParams params);
    
    /**
     * Destructor - ensures all resources are properly released
     */
    ~VrchatBoard () override;

    /**
     * Prepare the board for data acquisition
     * - Creates UDP sockets for data reception and control
     * - Binds data socket to specified port
     * - If no IP provided: Auto-discovers board via beacon
     * - If IP provided: Connects control socket to board IP
     * 
     * @return BrainFlowExitCodes::STATUS_OK on success
     *         BrainFlowExitCodes::BOARD_NOT_READY_ERROR if discovery fails
     */
    int prepare_session () override;
    
    /**
     * Prepare session with explicit discovery and custom timeout. Forces auto-discovery even if IP is set in params.
     * 
     * @param timeout_ms Maximum time to wait for board discovery
     * @return BrainFlowExitCodes::STATUS_OK on success
     * 
     * Example: board.prepare_session_with_discovery(5000);  // 5 second timeout
     */
    int prepare_session_with_discovery (int timeout_ms);
    
    /**
     * Get the discovered board IP address
     * 
     * @return Board IP if discovered, empty string otherwise
     * 
     * Useful for displaying connection info or reconnecting
     */
    std::string get_discovered_ip () const;
    
    /**
     * Start streaming EEG data from the board
     * - Launches data reception thread
     * - Launches keep-alive thread
     * @param buffer_size Size of BrainFlow's ring buffer
     * @param streamer_params Optional parameters for data streamers
     * @return BrainFlowExitCodes::STATUS_OK on success
     */
    int start_stream (int buffer_size, const char *streamer_params) override;
    
    /**
     * Stop streaming EEG data
     * - Signals threads to stop
     * - Waits for threads to finish
     * @return BrainFlowExitCodes::STATUS_OK on success
     */
    int stop_stream () override;
    
    /**
     * Release all board resources
     * - Stops streaming if active
     * - Closes all sockets
     * - Frees memory
     * @return BrainFlowExitCodes::STATUS_OK on success
     */
    int release_session () override;
    
    /**
     * Send configuration command to the board
     * 
     * Supported commands include:
     * - Filter control (sys filters_on/off, etc.)
     * - Settings (sys digitalgain, sys dccutofffreq, etc.)
     * - Board management (sys esp_reboot, sys adc_reset, etc.)
     * 
     * @param config Command string to send
     * @param response[out] Board's response (if any)
     * @return BrainFlowExitCodes::STATUS_OK on success
     */
    int config_board (std::string config, std::string &response) override;

private:
    // ====================================================================
    //                      PRIVATE METHODS
    // ====================================================================
    
    /**
     * Worker thread for receiving and processing EEG data
     * - Receives UDP packets containing EEG frames
     * - Parses 24-bit samples from 16 channels  
     * - Pushes data to BrainFlow's ring buffer
     */
    void read_thread ();
    
    /**
     * Worker thread for sending keep-alive messages
     * - Sends "floof" message every 5 seconds
     * - Maintains UDP connection state
     */
    void ping_thread ();
    
    /**
     * Helper to close and delete all socket objects
     */
    void close_sockets ();

    // ====================================================================
    //                      MEMBER VARIABLES
    // ====================================================================
    
    // ---------- Network Sockets ----------
    SocketServerUDP *data_srv_ { nullptr };  // Receives EEG data packets. Initialized to nullptr for safe
                                             // cleanup (delete nullptr is safe) and to detect if socket was created.
    int ctrl_socket_ { -1 };                 // Control socket (raw socket for send/recv). Initialize to -1 (invalid
                                             // file descriptor) to detect if socket is open. Valid sockets are always >= 0.
    std::mutex ctrl_mutex_;                  // Thread safety lock - prevents ping and config from interfering

    // ---------- Thread Management ----------
    std::atomic<bool> keep_alive_ { false }; // Thread control flag. Atomic ensures read/write operations are thread-safe
                                             // without mutex overhead. Critical here because read_thread checks this
                                             // in tight loop while main thread may set it during stop_stream().
    std::atomic<bool> keep_floof_ { false };
    std::thread read_th_;                    // Data reception thread - continuously reads EEG packets
    std::thread ping_th_;                    // Keep-alive thread - sends periodic "hello" messages

    // ---------- State Tracking ----------
    bool initialized_ { false };             // Session prepared flag. True after prepare_session() succeeds.
                                             // Prevents operations on unopened sockets/uninitialized resources.
    bool streaming_   { false };             // Stream active flag. True between start_stream() and stop_stream().
                                             // Tracked separately from initialized_ because you can prepare/release
                                             // session multiple times while streaming, or start/stop stream
                                             // multiple times within one session.

    // ---------- Network Configuration ----------
    int data_port_ { 5001 };                 // UDP port for data reception (default)
    int ctrl_port_ { 5000 };                 // UDP port for control commands (default)
    
    // ---------- Auto-discovery ----------
    std::string discovered_ip_ { "" };       // Board IP discovered from beacon
    std::string board_ip_ { "" };            // Board IP for sending commands
    
    // ---------- Platform-specific ----------
#ifdef _WIN32
    bool wsa_initialized_ { false };         // Track Windows socket initialization. WSAStartup must be called
                                             // before any socket operations on Windows, and WSACleanup must match.
                                             // This flag prevents multiple init/cleanup calls which would fail.
#endif
    
    // ---------- Timestamp Alignment ----------
    bool first_packet_received_ { false };    // Flag to track first packet
    double timestamp_offset_ { 0.0 };         // Offset to convert hw time to PC time
    
    /**
     * Wait for board beacon and discover IP address. Uses raw sockets to extract sender's IP from UDP beacon.
     * 
     * @param timeout_ms Maximum time to wait in milliseconds
     * @return true if board discovered, false if timeout
     */
    bool wait_for_beacon (int timeout_ms);
};