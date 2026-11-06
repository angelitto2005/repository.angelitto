#include "common.h"

#include <atomic>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <mutex>

#ifdef __ANDROID__
#include <android/log.h>
#include <sys/syscall.h>
#include <unistd.h>
#endif

namespace engine
{

namespace
{
std::atomic<LogFn> gLog{nullptr};

void DefaultLog(LogLevel level, const char* message)
{
  const char* prefix = level == LogLevel::Error
                           ? "vfs.tmdbm error: "
                           : level == LogLevel::Warning ? "vfs.tmdbm warning: " : "vfs.tmdbm: ";
  std::fprintf(stderr, "%s%s\n", prefix, message);
}
}  // namespace

void SetLog(LogFn fn)
{
  gLog.store(fn ? fn : &DefaultLog);
}

void Trace(const char* fmt, ...)
{
  char message[1024];
  va_list args;
  va_start(args, fmt);
  std::vsnprintf(message, sizeof(message), fmt, args);
  va_end(args);
#ifdef __ANDROID__
  __android_log_print(ANDROID_LOG_INFO, "vfs.tmdbm-trace", "[%ld] %s",
                      static_cast<long>(syscall(SYS_gettid)), message);
#else
  std::fprintf(stderr, "%s\n", message);
#endif
}

void Log(LogLevel level, const char* fmt, ...)
{
  char message[2048];
  va_list args;
  va_start(args, fmt);
  std::vsnprintf(message, sizeof(message), fmt, args);
  va_end(args);
  LogFn fn = gLog.load();
  if (fn == nullptr)
    DefaultLog(level, message);
  else
    fn(level, message);
}

bool Base64Decode(const std::string& text, std::string& out)
{
  out.clear();
  int value = 0;
  int bits = -8;
  for (unsigned char ch : text)
  {
    int digit;
    if (ch >= 'A' && ch <= 'Z')
      digit = ch - 'A';
    else if (ch >= 'a' && ch <= 'z')
      digit = ch - 'a' + 26;
    else if (ch >= '0' && ch <= '9')
      digit = ch - '0' + 52;
    else if (ch == '+' || ch == '-')
      digit = 62;
    else if (ch == '/' || ch == '_')
      digit = 63;
    else if (ch == '=')
      continue;
    else if (ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n')
      continue;
    else
      return false;
    value = (value << 6) | digit;
    bits += 6;
    if (bits >= 0)
    {
      out.push_back(static_cast<char>((value >> bits) & 0xFF));
      bits -= 8;
    }
  }
  return true;
}

uint32_t Crc32(const void* data, size_t size, uint32_t seed)
{
  static uint32_t table[256];
  static std::once_flag once;
  std::call_once(once,
                 []()
                 {
                   for (uint32_t index = 0; index < 256; ++index)
                   {
                     uint32_t value = index;
                     for (int bit = 0; bit < 8; ++bit)
                       value = (value & 1) ? (0xEDB88320u ^ (value >> 1)) : (value >> 1);
                     table[index] = value;
                   }
                 });
  uint32_t crc = seed ^ 0xFFFFFFFFu;
  const auto* bytes = static_cast<const uint8_t*>(data);
  for (size_t index = 0; index < size; ++index)
    crc = table[(crc ^ bytes[index]) & 0xFF] ^ (crc >> 8);
  return crc ^ 0xFFFFFFFFu;
}

std::string Trim(const std::string& text)
{
  size_t start = 0;
  size_t end = text.size();
  while (start < end && (text[start] == ' ' || text[start] == '\t' || text[start] == '\r' ||
                         text[start] == '\n'))
    ++start;
  while (end > start && (text[end - 1] == ' ' || text[end - 1] == '\t' ||
                         text[end - 1] == '\r' || text[end - 1] == '\n'))
    --end;
  return text.substr(start, end - start);
}

bool StartsWith(const std::string& text, const char* prefix)
{
  const size_t length = std::strlen(prefix);
  return text.size() >= length && std::memcmp(text.data(), prefix, length) == 0;
}

std::string Lower(const std::string& text)
{
  std::string out = text;
  for (char& ch : out)
    if (ch >= 'A' && ch <= 'Z')
      ch = static_cast<char>(ch - 'A' + 'a');
  return out;
}

}  // namespace engine
