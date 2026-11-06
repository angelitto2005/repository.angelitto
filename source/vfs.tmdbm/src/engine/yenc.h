#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace engine
{

struct YencResult
{
  bool ok = false;
  std::string error;
  std::vector<uint8_t> data;
  int64_t begin = 0;
  int64_t size = 0;
  int64_t part_end = 0;
  bool crc_ok = true;
};

YencResult YencDecode(const std::vector<uint8_t>& article);

}  // namespace engine
