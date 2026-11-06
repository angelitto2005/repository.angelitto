#include "yenc.h"

#include "common.h"

#include <algorithm>
#include <cstring>

namespace engine
{

namespace
{
const char kBegin[] = "=ybegin";
const char kPart[] = "=ypart";
const char kEnd[] = "=yend";

size_t FindBytes(const std::vector<uint8_t>& data, size_t from, const char* needle)
{
  const size_t length = std::strlen(needle);
  if (from >= data.size() || length > data.size() - from)
    return std::string::npos;
  const auto found = std::search(data.begin() + static_cast<std::ptrdiff_t>(from), data.end(),
                                 needle, needle + length);
  if (found == data.end())
    return std::string::npos;
  return static_cast<size_t>(found - data.begin());
}

size_t FindLast(const std::vector<uint8_t>& data, const char* needle)
{
  const size_t length = std::strlen(needle);
  if (length > data.size())
    return std::string::npos;
  for (size_t position = data.size() - length + 1; position-- > 0;)
    if (std::memcmp(data.data() + position, needle, length) == 0)
      return position;
  return std::string::npos;
}

std::string LineAt(const std::vector<uint8_t>& data, size_t start)
{
  if (start >= data.size())
    return std::string();
  size_t end = start;
  while (end < data.size() && data[end] != '\n')
    ++end;
  std::string line(reinterpret_cast<const char*>(data.data() + start), end - start);
  if (!line.empty() && line.back() == '\r')
    line.pop_back();
  return line;
}

void ParseHeader(const std::string& line, int64_t& size, int64_t& begin, int64_t& end,
                 std::string& part_crc, std::string& file_crc)
{
  size_t position = 0;
  while (position < line.size())
  {
    while (position < line.size() && (line[position] == ' ' || line[position] == '\t'))
      ++position;
    const size_t start = position;
    while (position < line.size() && line[position] != ' ' && line[position] != '\t')
      ++position;
    const std::string token = line.substr(start, position - start);
    const size_t equals = token.find('=');
    if (equals == std::string::npos)
      continue;
    const std::string key = Lower(token.substr(0, equals));
    const std::string value = token.substr(equals + 1);
    auto number = [&value](int64_t& target)
    {
      try
      {
        size_t used = 0;
        const long long parsed = std::stoll(value, &used);
        if (used == value.size())
          target = parsed;
      }
      catch (...)
      {
      }
    };
    if (key == "size")
      number(size);
    else if (key == "begin")
    {
      number(begin);
      if (begin > 0)
        --begin;
    }
    else if (key == "end")
      number(end);
    else if (key == "pcrc32")
      part_crc = value;
    else if (key == "crc32")
      file_crc = value;
  }
}

std::string StripName(const std::string& line)
{
  size_t at = line.find(" name=");
  if (at == std::string::npos && line.rfind("name=", 0) == 0)
    at = 0;
  return at == std::string::npos ? line : line.substr(0, at);
}
}  // namespace

YencResult YencDecode(const std::vector<uint8_t>& article)
{
  YencResult result;
  if (article.empty())
  {
    result.error = "empty article";
    return result;
  }
  const size_t begin_at = FindBytes(article, 0, kBegin);
  if (begin_at == std::string::npos)
  {
    result.error = "no =ybegin in this article";
    return result;
  }
  size_t line_end = begin_at;
  while (line_end < article.size() && article[line_end] != '\n')
    ++line_end;
  if (line_end >= article.size())
  {
    result.error = "truncated =ybegin";
    return result;
  }
  const std::string begin_line = StripName(LineAt(article, begin_at));
  int64_t total_size = 0;
  int64_t ignored_begin = 0;
  int64_t ignored_end = 0;
  std::string ignored_crc;
  std::string ignored_file_crc;
  ParseHeader(begin_line, total_size, ignored_begin, ignored_end, ignored_crc, ignored_file_crc);

  size_t position = line_end + 1;
  int64_t part_begin = 0;
  int64_t part_end = 0;
  bool has_part = false;
  if (position + 6 <= article.size() &&
      std::memcmp(article.data() + position, kPart, 6) == 0)
  {
    has_part = true;
    size_t part_line_end = position;
    while (part_line_end < article.size() && article[part_line_end] != '\n')
      ++part_line_end;
    if (part_line_end >= article.size())
    {
      result.error = "truncated =ypart";
      return result;
    }
    ParseHeader(LineAt(article, position), ignored_begin, part_begin, part_end, ignored_crc,
                ignored_file_crc);
    position = part_line_end + 1;
  }

  const size_t end_at = FindLast(article, kEnd);
  std::string part_crc;
  std::string file_crc;
  if (end_at != std::string::npos)
  {
    const std::string end_line = LineAt(article, end_at);
    int64_t ignored = 0;
    ParseHeader(end_line, ignored, ignored_begin, ignored_end, part_crc, file_crc);
  }

  const size_t body_end = end_at == std::string::npos ? article.size() : end_at;
  result.data.reserve(body_end > position ? (body_end - position) * 3 / 4 : 0);
  for (size_t index = position; index < body_end; ++index)
  {
    const uint8_t value = article[index];
    if (value == '\r' || value == '\n')
      continue;
    if (value == '=')
    {
      if (index + 1 < body_end)
        result.data.push_back(static_cast<uint8_t>(article[++index] - 106));
      continue;
    }
    result.data.push_back(static_cast<uint8_t>(value - 42));
  }
  if (result.data.empty())
  {
    result.error = "no payload";
    return result;
  }

  result.begin = has_part ? part_begin : 0;
  result.part_end = has_part ? part_end : static_cast<int64_t>(result.data.size());
  result.size = total_size > 0 ? total_size : result.part_end;

  const std::string& wanted = has_part ? part_crc : file_crc;
  if (!wanted.empty())
  {
    try
    {
      const uint32_t expected = static_cast<uint32_t>(std::stoul(wanted, nullptr, 16));
      result.crc_ok = Crc32(result.data.data(), result.data.size()) == expected;
    }
    catch (...)
    {
      result.crc_ok = true;
    }
  }
  result.ok = true;
  return result;
}

}  // namespace engine
