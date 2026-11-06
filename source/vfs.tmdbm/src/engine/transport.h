#pragma once

#include <cstddef>
#include <memory>
#include <string>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
using SocketHandle = SOCKET;
constexpr SocketHandle kBadSocket = INVALID_SOCKET;
#else
using SocketHandle = int;
constexpr SocketHandle kBadSocket = -1;
#endif

namespace engine
{

class Transport
{
public:
  virtual ~Transport() = default;
  virtual int Recv(void* data, size_t size, std::string& error) = 0;
  virtual bool SendAll(const void* data, size_t size, std::string& error) = 0;
  virtual void Close() = 0;
};

std::unique_ptr<Transport> ConnectTcp(const std::string& host, int port, int timeout,
                                      std::string& error);

std::unique_ptr<Transport> ConnectTls(const std::string& host, int port, int timeout,
                                      const std::string& cacert, std::string& error);

}  // namespace engine
