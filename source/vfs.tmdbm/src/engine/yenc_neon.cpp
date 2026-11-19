#include <cstddef>
#include <cstdint>

#if defined(__ANDROID__)

#include <arm_neon.h>
#include <elf.h>
#include <sys/auxv.h>

#ifndef HWCAP_NEON
#define HWCAP_NEON (1 << 12)
#endif

namespace engine
{

bool YencNeonAvailable()
{
#if defined(__aarch64__)
  return true;
#else
  static const bool available = (getauxval(AT_HWCAP) & HWCAP_NEON) != 0;
  return available;
#endif
}

// Copies a run of yEnc body bytes while it holds no CR, LF or '='; returns the
// number of input bytes consumed, always a multiple of 16.
size_t YencNeonClean(const uint8_t* source, size_t count, uint8_t* target)
{
  const uint8x16_t line_feed = vdupq_n_u8('\n');
  const uint8x16_t carriage = vdupq_n_u8('\r');
  const uint8x16_t escape = vdupq_n_u8('=');
  const uint8x16_t offset = vdupq_n_u8(42);
  size_t used = 0;
  while (count - used >= 16)
  {
    const uint8x16_t chunk = vld1q_u8(source + used);
    const uint8x16_t flags = vorrq_u8(
        vorrq_u8(vceqq_u8(chunk, line_feed), vceqq_u8(chunk, carriage)),
        vceqq_u8(chunk, escape));
#if defined(__aarch64__)
    const bool special = vmaxvq_u8(flags) != 0;
#else
    const uint64x2_t bits = vreinterpretq_u64_u8(flags);
    const bool special = (vgetq_lane_u64(bits, 0) | vgetq_lane_u64(bits, 1)) != 0;
#endif
    if (special)
      break;
    vst1q_u8(target + used, vsubq_u8(chunk, offset));
    used += 16;
  }
  return used;
}

}  // namespace engine

#endif
