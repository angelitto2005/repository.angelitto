#include "plan.h"

#include "common.h"

#include <cerrno>
#include <cstdlib>
#include <unordered_map>

namespace engine
{

namespace
{
std::vector<std::string> Fields(const std::string& line)
{
  std::vector<std::string> found;
  size_t position = 0;
  while (position < line.size())
  {
    while (position < line.size() && (line[position] == ' ' || line[position] == '\t'))
      ++position;
    if (position >= line.size())
      break;
    const size_t start = position;
    while (position < line.size() && line[position] != ' ' && line[position] != '\t')
      ++position;
    found.push_back(line.substr(start, position - start));
  }
  return found;
}

std::string Rest(const std::string& line, size_t offset)
{
  while (offset < line.size() && (line[offset] == ' ' || line[offset] == '\t'))
    ++offset;
  return line.substr(offset);
}

int64_t Number(const std::string& text, int line_number, const char* what)
{
  try
  {
    size_t used = 0;
    const long long value = std::stoll(text, &used);
    if (used != text.size())
      throw std::invalid_argument("trailing");
    return value;
  }
  catch (...)
  {
    throw PlanError("line " + std::to_string(line_number) + ": bad " + what + " '" + text + "'");
  }
}

double Decimal(const std::string& text, int line_number, const char* what)
{
  try
  {
    size_t used = 0;
    const double value = std::stod(text, &used);
    if (used != text.size())
      throw std::invalid_argument("trailing");
    return value;
  }
  catch (...)
  {
    throw PlanError("line " + std::to_string(line_number) + ": bad " + what + " '" + text + "'");
  }
}

std::string Decoded(const std::string& text, int line_number, const char* what)
{
  std::string out;
  if (!Base64Decode(text, out))
    throw PlanError("line " + std::to_string(line_number) + ": bad " + what);
  return out;
}

bool Flag(const std::string& text, int line_number, const char* what)
{
  const int64_t value = Number(text, line_number, what);
  if (value != 0 && value != 1)
    throw PlanError("line " + std::to_string(line_number) + ": " + what + " must be 0 or 1");
  return value != 0;
}
}  // namespace

Plan Plan::Parse(const std::string& text)
{
  Plan plan;
  bool header = false;
  int line_number = 0;
  std::unordered_map<int, size_t> part_index;

  size_t start = 0;
  while (start <= text.size())
  {
    size_t end = text.find('\n', start);
    if (end == std::string::npos)
      end = text.size();
    std::string line = text.substr(start, end - start);
    start = end + 1;
    ++line_number;
    if (!line.empty() && line.back() == '\r')
      line.pop_back();
    if (line.empty() || line[0] == '#')
      continue;

    const std::vector<std::string> fields = Fields(line);
    if (fields.empty())
      continue;
    const std::string& kind = fields[0];

    if (!header)
    {
      if (kind != "tmdbm-plan" || fields.size() < 2 || fields[1] != "1")
        throw PlanError("line " + std::to_string(line_number) + ": not a tmdbm plan");
      header = true;
      continue;
    }

    if (kind == "token" && fields.size() >= 2)
      plan.token = fields[1];
    else if (kind == "name")
      plan.name = Trim(Rest(line, 4));
    else if (kind == "container" && fields.size() >= 2)
      plan.container = Lower(fields[1]);
    else if (kind == "length" && fields.size() >= 2)
      plan.length = Number(fields[1], line_number, "length");
    else if (kind == "timeout" && fields.size() >= 2)
      plan.timeout = static_cast<int>(Number(fields[1], line_number, "timeout"));
    else if (kind == "prefetch" && fields.size() >= 2)
      plan.prefetch = Number(fields[1], line_number, "prefetch");
    else if (kind == "cache" && fields.size() >= 2)
      plan.cache = Number(fields[1], line_number, "cache");
    else if (kind == "pipeline" && fields.size() >= 2)
      plan.pipeline = static_cast<int>(Number(fields[1], line_number, "pipeline"));
    else if (kind == "workers" && fields.size() >= 2)
      plan.workers = static_cast<int>(Number(fields[1], line_number, "workers"));
    else if (kind == "holefilling" && fields.size() >= 2)
      plan.hole_filling = Flag(fields[1], line_number, "holefilling");
    else if (kind == "holepercent" && fields.size() >= 2)
      plan.hole_percent = Decimal(fields[1], line_number, "holepercent");
    else if (kind == "holeconsecutive" && fields.size() >= 2)
      plan.hole_consecutive = static_cast<int>(Number(fields[1], line_number, "holeconsecutive"));
    else if (kind == "cacert")
      plan.cacert = Rest(line, 6);
    else if (kind == "server")
    {
      if (fields.size() < 8)
        throw PlanError("line " + std::to_string(line_number) + ": server needs 7 values");
      ServerConfig server;
      server.host = fields[1];
      server.port = static_cast<int>(Number(fields[2], line_number, "port"));
      server.tls = Flag(fields[3], line_number, "tls");
      server.connections = static_cast<int>(Number(fields[4], line_number, "connections"));
      server.backup = Flag(fields[5], line_number, "backup");
      server.user = Decoded(fields[6], line_number, "user");
      server.password = Decoded(fields[7], line_number, "password");
      server.label = fields.size() >= 9 ? Decoded(fields[8], line_number, "label") : server.host;
      if (server.host.empty() || server.port <= 0 || server.port > 65535)
        throw PlanError("line " + std::to_string(line_number) + ": bad server address");
      if (server.connections < 1)
        server.connections = 1;
      if (server.label.empty())
        server.label = server.host;
      plan.servers.push_back(server);
    }
    else if (kind == "part")
    {
      if (fields.size() < 5)
        throw PlanError("line " + std::to_string(line_number) + ": part needs 4 values");
      PlanPart part;
      part.id = static_cast<int>(Number(fields[1], line_number, "part id"));
      part.skip = Number(fields[2], line_number, "skip");
      part.length = Number(fields[3], line_number, "part length");
      part.part_size = Number(fields[4], line_number, "part size");
      if (part.skip < 0 || part.length < 0 || part.part_size < 0)
        throw PlanError("line " + std::to_string(line_number) + ": negative part value");
      if (part_index.count(part.id))
        throw PlanError("line " + std::to_string(line_number) + ": duplicate part id");
      part_index[part.id] = plan.parts.size();
      plan.parts.push_back(std::move(part));
    }
    else if (kind == "a")
    {
      if (fields.size() < 3)
        throw PlanError("line " + std::to_string(line_number) + ": article needs a part and id");
      const int id = static_cast<int>(Number(fields[1], line_number, "article part"));
      const auto found = part_index.find(id);
      if (found == part_index.end())
        throw PlanError("line " + std::to_string(line_number) + ": article for unknown part");
      std::string message_id = fields[2];
      if (!message_id.empty() && message_id.front() == '<')
        message_id.erase(message_id.begin());
      if (!message_id.empty() && message_id.back() == '>')
        message_id.pop_back();
      if (message_id.empty())
        throw PlanError("line " + std::to_string(line_number) + ": empty article id");
      plan.parts[found->second].articles.push_back(std::move(message_id));
    }
  }

  if (!header)
    throw PlanError("empty plan");
  if (plan.servers.empty())
    throw PlanError("no Usenet provider in this plan");
  if (plan.parts.empty())
    throw PlanError("no file part in this plan");
  int64_t total = 0;
  for (PlanPart& part : plan.parts)
  {
    if (part.articles.empty())
      throw PlanError("part " + std::to_string(part.id) + " has no articles");
    part.media_start = total;
    total += part.length;
  }
  if (plan.length <= 0)
    plan.length = total;
  else if (plan.length != total)
  {
    Log(LogLevel::Warning, "plan length %lld does not match the parts (%lld), using the parts",
        static_cast<long long>(plan.length), static_cast<long long>(total));
    plan.length = total;
  }
  if (plan.length <= 0)
    throw PlanError("this plan has no length");
  if (plan.pipeline < 1)
    plan.pipeline = 1;
  if (plan.pipeline > 8)
    plan.pipeline = 8;
  if (plan.workers < 1)
    plan.workers = 1;
  if (plan.workers > 64)
    plan.workers = 64;
  if (plan.timeout < 1)
    plan.timeout = 20;
  if (plan.prefetch < 1024 * 1024)
    plan.prefetch = 1024 * 1024;
  if (plan.cache < plan.prefetch + 4 * 1024 * 1024)
    plan.cache = plan.prefetch + 4 * 1024 * 1024;
  return plan;
}

int Plan::FindPart(int id) const
{
  for (size_t index = 0; index < parts.size(); ++index)
    if (parts[index].id == id)
      return static_cast<int>(index);
  return -1;
}

}  // namespace engine
