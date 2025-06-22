#ifndef MESSAGES_LIB_H
#define MESSAGES_LIB_H

// ---------------------------------------------------------------------------------------------------------------------------------
// Includes
// ---------------------------------------------------------------------------------------------------------------------------------
#include <WiFiUdp.h>   // WiFiUDP
#include <SPI.h>       // SPIClass
#include <stdint.h>
#include <net_manager.h>




// MsgContext  – shared pointers the parser needs (populated in main.cpp)
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
struct MsgContext
{
    WiFiUDP *    udp;         // raw socket for parser replies
    SPIClass *   spi;         // SPI handle if helpers need it
    const char * udp_ip;      // PC IP (string form)
    uint16_t     udp_port_pc_ctrl; // PC UDP port
};




// API
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void msg_init(const MsgContext *ctx);         // called from setup()
void parse_and_execute_command(void);         // called every loop()




// Family handlers (implemented in .cpp)
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void handle_SPI(char **ctx, const char *orig);
void handle_SYS(char **ctx, const char *orig);
void handle_USR(char **ctx, const char *orig);  // placeholder

#endif // MESSAGES_LIB_H
