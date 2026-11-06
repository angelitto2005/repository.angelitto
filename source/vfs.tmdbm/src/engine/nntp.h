#pragma once

#include "plan.h"
#include "transport.h"

#include <atomic>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace engine
{

class NntpError : public std::runtime_error
{
public:
  NntpError(const std::string& message, int code = 0)
    : std::runtime_error(message), code_(code)
  {
  }
  int Code() const { return code_; }

private:
  int code_;
};

class NntpAuthError : public NntpError
{
public:
  using NntpError::NntpError;
};

class NntpTooManyError : public NntpError
{
public:
  using NntpError::NntpError;
};

struct NntpReply
{
  bool missing = false;
  std::vector<uint8_t> body;
};

class NntpConnection
{
public:
  NntpConnection(const ServerConfig& server, int timeout,
                 const std::string& cacert = std::string());
  ~NntpConnection();

  NntpConnection(const NntpConnection&) = delete;
  NntpConnection& operator=(const NntpConnection&) = delete;

  std::vector<NntpReply> BodyMany(const std::vector<std::string>& message_ids);
  const std::string& Greeting() const { return greeting_; }
  void Abort();

private:
  void Fill();
  std::string ReadLine();
  std::vector<uint8_t> ReadPayload();
  std::pair<int, std::string> Reply();
  std::pair<int, std::string> Command(const std::string& text);

  std::unique_ptr<Transport> transport_;
  std::string buffer_;
  std::string greeting_;
  std::atomic<bool> closed_{false};
};

}  // namespace engine
