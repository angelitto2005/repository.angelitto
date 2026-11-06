#include "engine/common.h"
#include "engine/plan.h"
#include "engine/stream.h"

#include <kodi/AddonBase.h>
#include <kodi/Filesystem.h>
#include <kodi/General.h>
#include <kodi/addon-instance/VFS.h>

#include <cstdio>
#include <memory>
#include <string>
#include <sys/types.h>
#include <vector>

#ifdef __ANDROID__
#include <android/log.h>
#endif

namespace
{
constexpr const char* PROTOCOL = "tmdbm";
constexpr const char* PLAN_FOLDER =
    "special://profile/addon_data/plugin.video.tmdbmovies/usenet-vfs/";
constexpr int CHUNK_SIZE = 256 * 1024;

struct FileHandle
{
  std::shared_ptr<engine::Stream> stream;
  int64_t position{0};
  bool error_logged{false};
};

void EngineLog(engine::LogLevel level, const char* message)
{
  const ADDON_LOG kodi_level =
      level == engine::LogLevel::Error
          ? ADDON_LOG_ERROR
          : level == engine::LogLevel::Warning ? ADDON_LOG_WARNING : ADDON_LOG_INFO;
#ifdef __ANDROID__
  __android_log_print(ANDROID_LOG_INFO, "vfs.tmdbm-log", "%s", message);
#endif
  kodi::Log(kodi_level, "vfs.tmdbm: %s", message);
}

int HexDigit(char value)
{
  if (value >= '0' && value <= '9')
    return value - '0';
  if (value >= 'a' && value <= 'f')
    return value - 'a' + 10;
  if (value >= 'A' && value <= 'F')
    return value - 'A' + 10;
  return -1;
}

std::string PercentDecode(const std::string& value)
{
  std::string out;
  out.reserve(value.size());
  for (size_t i = 0; i < value.size(); ++i)
  {
    if (value[i] == '%' && i + 2 < value.size())
    {
      const int high = HexDigit(value[i + 1]);
      const int low = HexDigit(value[i + 2]);
      if (high >= 0 && low >= 0)
      {
        out.push_back(static_cast<char>((high << 4) | low));
        i += 2;
        continue;
      }
    }
    out.push_back(value[i]);
  }
  return out;
}

std::string FileName(const kodi::addon::VFSUrl& url)
{
  std::string name = url.GetFilename();
  const size_t options = name.find_first_of("|?");
  if (options != std::string::npos)
    name.resize(options);
  name = PercentDecode(name);
  const size_t slash = name.find_last_of("/\\");
  if (slash != std::string::npos)
    name = name.substr(slash + 1);
  return name;
}

bool ValidToken(const std::string& token)
{
  if (token.size() < 8 || token.size() > 64)
    return false;
  for (char value : token)
    if (!((value >= '0' && value <= '9') || (value >= 'a' && value <= 'f') ||
          (value >= 'A' && value <= 'F')))
      return false;
  return true;
}

std::string PlanPath(const std::string& token)
{
  return kodi::vfs::TranslateSpecialProtocol(PLAN_FOLDER) + token + ".plan";
}

std::string FirstPath(const std::string& token)
{
  return kodi::vfs::TranslateSpecialProtocol(PLAN_FOLDER) + token + ".first";
}

std::string WarmPath(const std::string& token)
{
  return kodi::vfs::TranslateSpecialProtocol(PLAN_FOLDER) + token + ".first2";
}

bool ReadTextFile(const std::string& path, std::string& text)
{
  kodi::vfs::CFile file;
  if (!file.OpenFile(path, ADDON_READ_NO_CACHE))
    return false;
  char buffer[64 * 1024];
  text.clear();
  for (;;)
  {
    const ssize_t got = file.Read(buffer, sizeof(buffer));
    if (got < 0)
      return false;
    if (got == 0)
      break;
    text.append(buffer, static_cast<size_t>(got));
  }
  return true;
}

bool LoadFirstArticle(const std::string& token, const engine::Plan& plan,
                      std::vector<uint8_t>& data)
{
  if (plan.parts.empty() || plan.parts[0].articles.empty())
    return false;
  std::string file;
  if (!ReadTextFile(FirstPath(token), file))
    return false;
  char message_id[512] = {0};
  long long length = 0;
  unsigned int crc = 0;
  if (std::sscanf(file.c_str(), "tmdbm-first 1 %511s %lld %x", message_id, &length, &crc) != 3)
    return false;
  const size_t line = file.find('\n');
  if (line == std::string::npos)
    return false;
  const size_t offset = line + 1;
  if (length < 0 || file.size() - offset != static_cast<size_t>(length))
    return false;
  if (plan.parts[0].articles[0] != message_id)
    return false;
  if (plan.parts[0].part_size > 0 && plan.parts[0].part_size != length)
    return false;
  data.assign(reinterpret_cast<const uint8_t*>(file.data() + offset),
              reinterpret_cast<const uint8_t*>(file.data() + file.size()));
  return engine::Crc32(data.data(), data.size()) == crc;
}

struct WarmArticle
{
  int index = 0;
  std::vector<uint8_t> data;
};

bool LoadWarmArticles(const std::string& token, const engine::Plan& plan,
                      std::vector<WarmArticle>& out)
{
  out.clear();
  if (plan.parts.empty() || plan.parts[0].articles.size() < 2)
    return false;
  std::string file;
  if (!ReadTextFile(WarmPath(token), file))
    return false;
  int count = 0;
  long long total = 0;
  if (std::sscanf(file.c_str(), "tmdbm-warm 1 %d %lld", &count, &total) != 2)
    return false;
  size_t offset = file.find('\n');
  if (offset == std::string::npos)
    return false;
  ++offset;
  if (count < 1 || count > 32 || total <= 0)
    return false;

  struct Entry
  {
    int index = 0;
    long long length = 0;
    unsigned int crc = 0;
  };
  std::vector<Entry> entries;
  entries.reserve(static_cast<size_t>(count));
  size_t sum = 0;
  for (int i = 0; i < count; ++i)
  {
    const size_t line = file.find('\n', offset);
    if (line == std::string::npos)
      return false;
    const std::string text = file.substr(offset, line - offset);
    char message_id[512] = {0};
    Entry entry;
    if (std::sscanf(text.c_str(), "%d %511s %lld %x", &entry.index, message_id,
                    &entry.length, &entry.crc) != 4)
      return false;
    if (entry.index < 1 ||
        static_cast<size_t>(entry.index) >= plan.parts[0].articles.size())
      return false;
    if (plan.parts[0].articles[entry.index] != message_id)
      return false;
    if (entry.length <= 0)
      return false;
    if (plan.parts[0].part_size > 0 && plan.parts[0].part_size != entry.length)
      return false;
    sum += static_cast<size_t>(entry.length);
    entries.push_back(entry);
    offset = line + 1;
  }
  if (static_cast<long long>(sum) != total ||
      file.size() - offset != static_cast<size_t>(total))
    return false;

  size_t position = offset;
  for (const Entry& entry : entries)
  {
    const size_t length = static_cast<size_t>(entry.length);
    if (position + length > file.size())
      return false;
    WarmArticle article;
    article.index = entry.index;
    article.data.assign(reinterpret_cast<const uint8_t*>(file.data() + position),
                        reinterpret_cast<const uint8_t*>(file.data() + position + length));
    if (engine::Crc32(article.data.data(), article.data.size()) != entry.crc)
    {
      out.clear();
      return false;
    }
    position += length;
    out.push_back(std::move(article));
  }
  return true;
}

bool LoadPlan(const std::string& token, std::shared_ptr<const engine::Plan>& plan,
              std::string& error)
{
  if (!ValidToken(token))
  {
    error = "bad stream token";
    return false;
  }
  const std::string path = PlanPath(token);
  std::string text;
  if (!ReadTextFile(path, text))
  {
    error = "the stream plan is missing";
    return false;
  }
  try
  {
    plan = std::make_shared<const engine::Plan>(engine::Plan::Parse(text));
  }
  catch (const std::exception& exception)
  {
    error = exception.what();
    return false;
  }
  return true;
}

bool UrlAllowed(const kodi::addon::VFSUrl& url)
{
  return url.GetProtocol() == PROTOCOL;
}

std::string PlanName(const engine::Plan& plan)
{
  const size_t slash = plan.name.find_last_of("/\\");
  return slash == std::string::npos ? plan.name : plan.name.substr(slash + 1);
}

bool MatchesPlan(const kodi::addon::VFSUrl& url, const engine::Plan& plan)
{
  const std::string name = FileName(url);
  const std::string wanted = PlanName(plan);
  if (name.empty() || wanted.empty())
    return false;
  return engine::Lower(name) == engine::Lower(wanted);
}
}  // namespace

class ATTR_DLL_LOCAL CUsenetVFS : public kodi::addon::CInstanceVFS
{
public:
  explicit CUsenetVFS(const kodi::addon::IInstanceInfo& instance) : CInstanceVFS(instance) {}

  kodi::addon::VFSFileHandle Open(const kodi::addon::VFSUrl& url) override
  {
    if (!UrlAllowed(url))
      return nullptr;
    std::shared_ptr<const engine::Plan> plan;
    std::string error;
    if (!LoadPlan(url.GetHostname(), plan, error))
    {
      kodi::Log(ADDON_LOG_ERROR, "vfs.tmdbm: cannot open %s: %s",
                url.GetHostname().c_str(), error.c_str());
      return nullptr;
    }
    if (!MatchesPlan(url, *plan))
      return nullptr;
    auto stream = std::make_shared<engine::Stream>(plan);
    std::vector<uint8_t> first;
    if (LoadFirstArticle(url.GetHostname(), *plan, first))
    {
      stream->PrimeFirstArticle(std::move(first));
      kodi::Log(ADDON_LOG_INFO, "vfs.tmdbm: the first article came from the plan cache");
      std::vector<WarmArticle> warm;
      if (LoadWarmArticles(url.GetHostname(), *plan, warm))
      {
        for (WarmArticle& article : warm)
          stream->PrimeArticle(article.index, std::move(article.data));
        kodi::Log(ADDON_LOG_INFO, "vfs.tmdbm: %d warm articles came from the plan cache",
                  static_cast<int>(warm.size()));
      }
    }
    if (!stream->Start(error))
    {
      kodi::Log(ADDON_LOG_ERROR, "vfs.tmdbm: cannot start %s: %s",
                url.GetHostname().c_str(), error.c_str());
      return nullptr;
    }
    const std::string name = FileName(url);
    kodi::Log(ADDON_LOG_INFO, "vfs.tmdbm: open %s (%s, %.1f MB, %d part(s))",
              url.GetHostname().c_str(), (name.empty() ? plan->name : name).c_str(),
              static_cast<double>(plan->length) / 1048576.0,
              static_cast<int>(plan->parts.size()));
    auto* handle = new FileHandle();
    handle->stream = stream;
    return handle;
  }

  bool Close(kodi::addon::VFSFileHandle context) override
  {
    auto* handle = static_cast<FileHandle*>(context);
    if (!handle)
      return false;
    engine::Trace("addon close begin");
    if (handle->stream)
      handle->stream->Close();
    engine::Trace("addon close end");
    delete handle;
    return true;
  }

  ssize_t Read(kodi::addon::VFSFileHandle context, uint8_t* buffer, size_t size) override
  {
    auto* handle = static_cast<FileHandle*>(context);
    if (!handle || !handle->stream)
      return -1;
    const int64_t got = handle->stream->Read(handle->position, buffer, size);
    if (got < 0)
    {
      if (!handle->error_logged)
      {
        handle->error_logged = true;
        kodi::Log(ADDON_LOG_ERROR, "vfs.tmdbm: read failed at %.1f MB: %s",
                  static_cast<double>(handle->position) / 1048576.0,
                  handle->stream->LastError().c_str());
      }
      return -1;
    }
    handle->position += got;
    return static_cast<ssize_t>(got);
  }

  int64_t Seek(kodi::addon::VFSFileHandle context, int64_t position, int whence) override
  {
    auto* handle = static_cast<FileHandle*>(context);
    if (!handle || !handle->stream)
      return -1;
    if (whence == SEEK_SET)
      handle->position = position;
    else if (whence == SEEK_CUR)
      handle->position += position;
    else if (whence == SEEK_END)
      handle->position = handle->stream->Length() + position;
    else
      return -1;
    if (handle->position < 0)
      handle->position = 0;
    if (handle->position > handle->stream->Length())
      handle->position = handle->stream->Length();
    return handle->position;
  }

  int64_t GetLength(kodi::addon::VFSFileHandle context) override
  {
    auto* handle = static_cast<FileHandle*>(context);
    return handle && handle->stream ? handle->stream->Length() : 0;
  }

  int64_t GetPosition(kodi::addon::VFSFileHandle context) override
  {
    auto* handle = static_cast<FileHandle*>(context);
    return handle ? handle->position : 0;
  }

  int GetChunkSize(kodi::addon::VFSFileHandle context) override { return CHUNK_SIZE; }

  bool IoControlGetSeekPossible(kodi::addon::VFSFileHandle context) override { return true; }

  int Stat(const kodi::addon::VFSUrl& url, kodi::vfs::FileStatus& buffer) override
  {
    if (!UrlAllowed(url))
      return -1;
    std::shared_ptr<const engine::Plan> plan;
    std::string error;
    if (!LoadPlan(url.GetHostname(), plan, error) || !MatchesPlan(url, *plan))
      return -1;
    buffer.SetSize(plan->length);
    buffer.SetAccessTime(0);
    buffer.SetModificationTime(0);
    buffer.SetStatusTime(0);
    buffer.SetIsRegular(true);
    return 0;
  }

  bool Exists(const kodi::addon::VFSUrl& url) override
  {
    if (!UrlAllowed(url))
      return false;
    std::shared_ptr<const engine::Plan> plan;
    std::string error;
    return LoadPlan(url.GetHostname(), plan, error) && MatchesPlan(url, *plan);
  }
};

class ATTR_DLL_LOCAL CMyAddon : public kodi::addon::CAddonBase
{
public:
  CMyAddon() { engine::SetLog(&EngineLog); }

  ADDON_STATUS CreateInstance(const kodi::addon::IInstanceInfo& instance,
                              KODI_ADDON_INSTANCE_HDL& hdl) override
  {
    if (!instance.IsType(ADDON_INSTANCE_VFS))
      return ADDON_STATUS_NOT_IMPLEMENTED;
    hdl = new CUsenetVFS(instance);
    return ADDON_STATUS_OK;
  }
};

ADDONCREATOR(CMyAddon)
