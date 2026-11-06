#include "engine/common.h"
#include "engine/plan.h"
#include "engine/stream.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <memory>
#include <string>
#include <thread>
#include <vector>

namespace
{
bool ReadFile(const std::string& path, std::string& text)
{
  std::FILE* file = std::fopen(path.c_str(), "rb");
  if (!file)
    return false;
  text.clear();
  char buffer[64 * 1024];
  size_t got = 0;
  while ((got = std::fread(buffer, 1, sizeof(buffer), file)) > 0)
    text.append(buffer, got);
  std::fclose(file);
  return true;
}
}  // namespace

int main(int argc, char** argv)
{
  if (argc < 2)
  {
    std::fprintf(stderr,
                 "usage: stream_test <plan> [--dump file] [--offset bytes] [--length bytes] "
                 "[--chunk bytes] [--close-after ms]\n");
    return 1;
  }
  const std::string plan_path = argv[1];
  std::string dump_path;
  int64_t offset = 0;
  int64_t length = -1;
  size_t chunk = 1024 * 1024;
  int close_after = -1;
  for (int index = 2; index < argc; ++index)
  {
    const std::string argument = argv[index];
    if (argument == "--dump" && index + 1 < argc)
      dump_path = argv[++index];
    else if (argument == "--offset" && index + 1 < argc)
      offset = std::atoll(argv[++index]);
    else if (argument == "--length" && index + 1 < argc)
      length = std::atoll(argv[++index]);
    else if (argument == "--chunk" && index + 1 < argc)
      chunk = static_cast<size_t>(std::atoll(argv[++index]));
    else if (argument == "--close-after" && index + 1 < argc)
      close_after = std::atoi(argv[++index]);
    else
    {
      std::fprintf(stderr, "unknown argument %s\n", argument.c_str());
      return 1;
    }
  }

  std::string text;
  if (!ReadFile(plan_path, text))
  {
    std::fprintf(stderr, "cannot read %s\n", plan_path.c_str());
    return 1;
  }
  std::shared_ptr<engine::Plan> plan;
  try
  {
    plan = std::make_shared<engine::Plan>(engine::Plan::Parse(text));
  }
  catch (const std::exception& exception)
  {
    std::fprintf(stderr, "plan: %s\n", exception.what());
    return 1;
  }

  engine::Stream stream(plan);
  std::string error;
  const auto started = std::chrono::steady_clock::now();
  if (!stream.Start(error))
  {
    std::fprintf(stderr, "start: %s\n", error.c_str());
    return 2;
  }
  std::thread closer;
  if (close_after >= 0)
    closer = std::thread(
        [&stream, close_after]()
        {
          std::this_thread::sleep_for(std::chrono::milliseconds(close_after));
          std::fprintf(stderr, "closing from the timer thread\n");
          stream.Close();
        });
  if (length < 0 || offset + length > stream.Length())
    length = stream.Length() - offset;
  if (length < 0)
    length = 0;
  if (chunk < 64 * 1024)
    chunk = 64 * 1024;

  std::FILE* dump = nullptr;
  if (!dump_path.empty())
  {
    dump = std::fopen(dump_path.c_str(), "wb");
    if (dump == nullptr)
    {
      std::fprintf(stderr, "cannot write %s\n", dump_path.c_str());
      stream.Close();
      return 1;
    }
  }

  std::vector<uint8_t> buffer(chunk);
  int64_t position = offset;
  int64_t end = offset + length;
  int64_t total = 0;
  uint32_t crc = 0;
  int exit_code = 0;
  while (position < end)
  {
    const size_t wanted = static_cast<size_t>(std::min<int64_t>(chunk, end - position));
    const int64_t got = stream.Read(position, buffer.data(), wanted);
    if (got < 0)
    {
      std::fprintf(stderr, "read failed at %lld: %s\n", static_cast<long long>(position),
                   stream.LastError().c_str());
      exit_code = 3;
      break;
    }
    if (got == 0)
      break;
    crc = engine::Crc32(buffer.data(), static_cast<size_t>(got), crc);
    if (dump != nullptr)
      std::fwrite(buffer.data(), 1, static_cast<size_t>(got), dump);
    position += got;
    total += got;
  }
  if (dump != nullptr)
    std::fclose(dump);

  const engine::StreamStats stats = stream.Stats();
  const double seconds =
      std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
  std::printf("length=%lld read=%lld crc32=%08x articles=%lld missing=%lld "
              "seconds=%.2f mbytes=%.2f\n",
              static_cast<long long>(stream.Length()), static_cast<long long>(total), crc,
              static_cast<long long>(stats.articles), static_cast<long long>(stats.missing),
              seconds, total / 1048576.0);
  std::fflush(stdout);
  stream.Close();
  if (closer.joinable())
    closer.join();
  return exit_code;
}
