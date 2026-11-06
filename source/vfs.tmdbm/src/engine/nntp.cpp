#include "nntp.h"

#include "common.h"

#include <algorithm>
#include <cstring>

namespace engine
{

namespace
{
constexpr size_t kRecvChunk = 256 * 1024;
constexpr size_t kMaxLine = 64 * 1024;

bool HasAny(const std::string& text, std::initializer_list<const char*> words)
{
  for (const char* word : words)
    if (text.find(word) != std::string::npos)
      return true;
  return false;
}

bool IsTooMany(int code, const std::string& text)
{
  if (code != 400 && code != 481 && code != 482 && code != 502)
    return false;
  const std::string low = Lower(text);
  return HasAny(low, {"too many", "connection", "limit", "session", "max"});
}

std::string Explain(int code, const std::string& text)
{
  const std::string low = Lower(text);
  if (HasAny(low, {"too many", "connection", "limit", "session", "max"}))
    return "the connection limit is reached - close other Usenet programs or lower the "
           "connections setting";
  if (HasAny(low, {"auth", "password", "passwd", "login", "credential", "invalid", "incorrect",
                   "failed", "unknown user", "rejected"}))
    return "the username or password was refused";
  if (HasAny(low, {"access", "permission", "not allowed", "blocked", "banned", "disabled",
                   "expired", "not permitted"}))
    return "this account is not allowed to connect";
  if (code == 481 || code == 482)
    return "the username or password was refused";
  if (code == 502)
    return "the server refused the session - check the username, the password and the IP";
  return "the login was refused";
}

std::string Angle(const std::string& message_id)
{
  std::string clean = Trim(message_id);
  if (!clean.empty() && clean.front() == '<')
    clean.erase(clean.begin());
  if (!clean.empty() && clean.back() == '>')
    clean.pop_back();
  return "<" + clean + ">";
}

bool IsMissing(int code)
{
  return code == 420 || code == 423 || code == 430;
}
}  // namespace

NntpConnection::NntpConnection(const ServerConfig& server, int timeout,
                               const std::string& cacert)
{
  std::string error;
  transport_ = server.tls ? ConnectTls(server.host, server.port, timeout, cacert, error)
                          : ConnectTcp(server.host, server.port, timeout, error);
  if (!transport_)
    throw NntpError("cannot connect to " + server.host + ": " + error);

  auto greeting = Reply();
  greeting_ = greeting.second;
  if (greeting.first != 200 && greeting.first != 201)
  {
    Abort();
    const std::string reason = "server said " + std::to_string(greeting.first) + " " +
                               greeting.second.substr(0, 80);
    if (IsTooMany(greeting.first, greeting.second))
      throw NntpTooManyError(reason + " - " + Explain(greeting.first, greeting.second),
                             greeting.first);
    throw NntpAuthError(reason + " - " + Explain(greeting.first, greeting.second),
                        greeting.first);
  }

  if (!server.user.empty())
  {
    auto reply = Command("AUTHINFO USER " + server.user);
    if (reply.first == 381)
      reply = Command("AUTHINFO PASS " + server.password);
    if (reply.first != 281)
    {
      Abort();
      const std::string reason =
          "login refused: " + std::to_string(reply.first) + " " + reply.second.substr(0, 60);
      if (IsTooMany(reply.first, reply.second))
        throw NntpTooManyError(reason + " - " + Explain(reply.first, reply.second),
                               reply.first);
      throw NntpAuthError(reason + " - " + Explain(reply.first, reply.second), reply.first);
    }
  }
}

NntpConnection::~NntpConnection()
{
  Abort();
}

void NntpConnection::Abort()
{
  if (closed_.exchange(true))
    return;
  if (transport_)
    transport_->Close();
}

void NntpConnection::Fill()
{
  char chunk[kRecvChunk];
  std::string error;
  const int got = transport_->Recv(chunk, sizeof(chunk), error);
  if (got < 0)
    throw NntpError("the connection failed: " + error);
  if (got == 0)
    throw NntpError("the server closed the connection");
  buffer_.append(chunk, static_cast<size_t>(got));
}

std::string NntpConnection::ReadLine()
{
  for (;;)
  {
    const size_t end = buffer_.find("\r\n");
    if (end != std::string::npos)
    {
      std::string line = buffer_.substr(0, end);
      buffer_.erase(0, end + 2);
      return line;
    }
    if (buffer_.size() > kMaxLine)
      throw NntpError("reply line too long");
    Fill();
  }
}

std::pair<int, std::string> NntpConnection::Reply()
{
  const std::string line = ReadLine();
  int code = 0;
  for (int index = 0; index < 3 && index < static_cast<int>(line.size()); ++index)
  {
    if (line[index] < '0' || line[index] > '9')
      break;
    code = code * 10 + (line[index] - '0');
  }
  if (code < 100 || code > 599)
    throw NntpError("bad reply '" + line.substr(0, 40) + "'");
  return {code, line.size() > 4 ? line.substr(4) : std::string()};
}

std::pair<int, std::string> NntpConnection::Command(const std::string& text)
{
  std::string error;
  if (!transport_->SendAll(text.data(), text.size(), error) ||
      !transport_->SendAll("\r\n", 2, error))
    throw NntpError("cannot send: " + error);
  return Reply();
}

std::vector<uint8_t> NntpConnection::ReadPayload()
{
  if (buffer_.size() >= 3 && buffer_.compare(0, 3, ".\r\n") == 0)
  {
    buffer_.erase(0, 3);
    return {};
  }

  for (;;)
  {
    const size_t end = buffer_.find("\r\n.\r\n");
    if (end != std::string::npos)
    {
      std::vector<uint8_t> data(buffer_.begin(),
                                buffer_.begin() + static_cast<std::ptrdiff_t>(end));
      buffer_.erase(0, end + 5);
      if (data.size() >= 2 && data[0] == '.' && data[1] == '.')
        data.erase(data.begin());
      for (size_t index = 0; index + 4 <= data.size();)
      {
        if (data[index] == '\r' && data[index + 1] == '\n' && data[index + 2] == '.' &&
            data[index + 3] == '.')
        {
          data.erase(data.begin() + static_cast<std::ptrdiff_t>(index + 2));
          index += 3;
        }
        else
        {
          ++index;
        }
      }
      return data;
    }
    Fill();
  }
}

std::vector<NntpReply> NntpConnection::BodyMany(const std::vector<std::string>& message_ids)
{
  std::vector<NntpReply> replies;
  replies.reserve(message_ids.size());
  if (message_ids.empty())
    return replies;

  std::string commands;
  commands.reserve(message_ids.size() * 96);
  for (const std::string& message_id : message_ids)
  {
    commands += "BODY ";
    commands += Angle(message_id);
    commands += "\r\n";
  }
  std::string error;
  if (!transport_->SendAll(commands.data(), commands.size(), error))
    throw NntpError("cannot send BODY: " + error);

  for (const std::string& message_id : message_ids)
  {
    auto reply = Reply();
    NntpReply found;
    if (IsMissing(reply.first))
    {
      found.missing = true;
      replies.push_back(std::move(found));
      continue;
    }
    if (reply.first != 222)
      throw NntpError("BODY " + Angle(message_id) + " answered " + std::to_string(reply.first) +
                          " " + reply.second.substr(0, 60),
                      reply.first);
    found.body = ReadPayload();
    replies.push_back(std::move(found));
  }
  return replies;
}

}  // namespace engine
