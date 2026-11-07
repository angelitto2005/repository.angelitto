#pragma once

#include "plan.h"

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace engine
{

struct ProviderStat
{
  int64_t articles = 0;
  int64_t bytes = 0;
  double seconds = 0;
};

struct StreamStats
{
  int64_t articles = 0;
  int64_t missing = 0;
  int64_t bytes = 0;
  double article_seconds = 0;
  std::map<std::string, ProviderStat> providers;
};

class Stream
{
public:
  explicit Stream(std::shared_ptr<const Plan> plan);
  ~Stream();

  Stream(const Stream&) = delete;
  Stream& operator=(const Stream&) = delete;

  bool Start(std::string& error);
  bool Usable() const;
  void PrimeFirstArticle(std::vector<uint8_t> data);
  void PrimeArticle(int index, std::vector<uint8_t> data);
  void Close();
  int64_t Length() const;
  int64_t Read(int64_t offset, uint8_t* dest, size_t size);
  StreamStats Stats() const;
  std::string LastError() const;

private:
  class Impl;
  std::shared_ptr<Impl> impl_;
};

}  // namespace engine
