/* stdendian.h — MinGW/Windows shim for Fathom's byte-swap needs */
#pragma once
#include <stdint.h>
#ifdef _MSC_VER
#  include <stdlib.h>
#  define bswap16(x) _byteswap_ushort(x)
#  define bswap32(x) _byteswap_ulong(x)
#  define bswap64(x) _byteswap_uint64(x)
#elif defined(__GNUC__)
#  define bswap16(x) __builtin_bswap16(x)
#  define bswap32(x) __builtin_bswap32(x)
#  define bswap64(x) __builtin_bswap64(x)
#else
static inline uint16_t bswap16(uint16_t x) { return (x>>8)|(x<<8); }
static inline uint32_t bswap32(uint32_t x) {
    return ((x>>24)&0xff)|((x>>8)&0xff00)|((x<<8)&0xff0000)|((x<<24)&0xff000000u);
}
static inline uint64_t bswap64(uint64_t x) {
    return ((uint64_t)bswap32(x&0xffffffff)<<32)|bswap32(x>>32);
}
#endif
