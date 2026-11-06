#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace engine
{

class PlanError : public std::runtime_error
{
public:
  explicit PlanError(const std::string& message) : std::runtime_error(message) {}
};

struct ServerConfig
{
  std::string host;
  int port = 563;
  bool tls = true;
  int connections = 4;
  bool backup = false;
  std::string user;
  std::string password;
  std::string label;
};

struct PlanPart
{
  int id = 0;
  int64_t skip = 0;
  int64_t length = 0;
  int64_t part_size = 0;
  int64_t media_start = 0;
  std::vector<std::string> articles;
};

struct Plan
{
  std::string token;
  std::string name;
  std::string container = "mkv";
  int64_t length = 0;
  int timeout = 20;
  int64_t prefetch = 12 * 1024 * 1024;
  int64_t cache = 36 * 1024 * 1024;
  int pipeline = 2;
  int workers = 0;
  bool hole_filling = true;
  double hole_percent = 2.0;
  int hole_consecutive = 4;
  std::string cacert;
  std::vector<ServerConfig> servers;
  std::vector<PlanPart> parts;

  static Plan Parse(const std::string& text);
  int FindPart(int id) const;
};

}  // namespace engine
