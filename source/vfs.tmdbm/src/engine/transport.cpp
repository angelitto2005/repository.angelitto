#include "transport.h"

#include "common.h"

#include <mbedtls/ctr_drbg.h>
#include <mbedtls/debug.h>
#include <mbedtls/entropy.h>
#include <mbedtls/error.h>
#include <mbedtls/net_sockets.h>
#include <mbedtls/ssl.h>
#include <mbedtls/x509_crt.h>
#include <psa/crypto.h>

#include <cerrno>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <utility>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <wincrypt.h>
#else
#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif
#endif

namespace engine
{

namespace
{
#ifdef _WIN32
void StartupSockets()
{
  static std::once_flag once;
  std::call_once(once,
                 []()
                 {
                   WSADATA data;
                   WSAStartup(MAKEWORD(2, 2), &data);
                 });
}

std::string SocketError(int code)
{
  switch (code)
  {
    case WSAETIMEDOUT:
      return "timeout";
    case WSAECONNREFUSED:
      return "connection refused";
    case WSAECONNRESET:
      return "connection reset";
    case WSAENETUNREACH:
      return "network unreachable";
    case WSAEHOSTUNREACH:
      return "host unreachable";
    default:
    {
      char text[256] = {};
      FormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS, nullptr,
                     static_cast<DWORD>(code), 0, text, sizeof(text), nullptr);
      std::string found(text);
      while (!found.empty() && (found.back() == '\r' || found.back() == '\n'))
        found.pop_back();
      if (found.empty())
        found = "socket error " + std::to_string(code);
      return found;
    }
  }
}

void SetTimeout(SocketHandle socket, int seconds)
{
  const DWORD timeout = static_cast<DWORD>(seconds) * 1000;
  setsockopt(socket, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&timeout),
             sizeof(timeout));
  setsockopt(socket, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&timeout),
             sizeof(timeout));
}
#else
void StartupSockets() {}

std::string SocketError(int code)
{
  if (code == EAGAIN || code == EWOULDBLOCK || code == ETIMEDOUT)
    return "timeout";
  return std::strerror(code);
}

void SetTimeout(SocketHandle socket, int seconds)
{
  timeval timeout{};
  timeout.tv_sec = seconds;
  setsockopt(socket, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
  setsockopt(socket, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
}
#endif

void ShutdownSocket(SocketHandle socket)
{
  if (socket == kBadSocket)
    return;
#ifdef _WIN32
  shutdown(socket, SD_BOTH);
#else
  shutdown(socket, SHUT_RDWR);
#endif
}

void CloseSocket(SocketHandle socket)
{
  if (socket == kBadSocket)
    return;
  ShutdownSocket(socket);
#ifdef _WIN32
  closesocket(socket);
#else
  close(socket);
#endif
}

class SocketTransport : public Transport
{
public:
  explicit SocketTransport(SocketHandle socket) : socket_(socket) {}
  ~SocketTransport() override { CloseSocket(socket_.exchange(kBadSocket)); }

  int Recv(void* data, size_t size, std::string& error) override
  {
    const SocketHandle socket = socket_.load();
    if (socket == kBadSocket)
    {
      error = "socket is closed";
      return -1;
    }
    for (;;)
    {
#ifdef _WIN32
      const int got = recv(socket, static_cast<char*>(data), static_cast<int>(size), 0);
      if (got == 0)
        return 0;
      if (got != SOCKET_ERROR)
        return got;
      const int code = WSAGetLastError();
      if (code == WSAEINTR)
        continue;
      error = SocketError(code);
      return -1;
#else
      const ssize_t got = recv(socket, data, size, 0);
      if (got == 0)
        return 0;
      if (got > 0)
        return static_cast<int>(got);
      if (errno == EINTR)
        continue;
      error = SocketError(errno);
      return -1;
#endif
    }
  }

  bool SendAll(const void* data, size_t size, std::string& error) override
  {
    const SocketHandle socket = socket_.load();
    if (socket == kBadSocket)
    {
      error = "socket is closed";
      return false;
    }
    const auto* bytes = static_cast<const char*>(data);
    size_t sent = 0;
    while (sent < size)
    {
#ifdef _WIN32
      const int done = send(socket, bytes + sent, static_cast<int>(size - sent), 0);
      if (done == SOCKET_ERROR)
      {
        const int code = WSAGetLastError();
        if (code == WSAEINTR)
          continue;
        error = SocketError(code);
        return false;
      }
#else
      const ssize_t done = send(socket, bytes + sent, size - sent, MSG_NOSIGNAL);
      if (done < 0)
      {
        if (errno == EINTR)
          continue;
        error = SocketError(errno);
        return false;
      }
#endif
      if (done == 0)
      {
        error = "the server closed the connection";
        return false;
      }
      sent += static_cast<size_t>(done);
    }
    return true;
  }

  void Close() override
  {
    ShutdownSocket(socket_.load());
  }

private:
  std::atomic<SocketHandle> socket_;
};

struct Address
{
  sockaddr_storage storage{};
  socklen_t length = 0;
  int family = AF_UNSPEC;
};

bool PrepareAddress(const addrinfo* info, Address& address)
{
  if (info->ai_addrlen > sizeof(address.storage))
    return false;
  std::memcpy(&address.storage, info->ai_addr, info->ai_addrlen);
  address.length = static_cast<socklen_t>(info->ai_addrlen);
  address.family = info->ai_family;
  return true;
}

SocketHandle OpenAddress(const Address& address, int timeout, std::string& error)
{
  const SocketHandle socket = ::socket(address.family, SOCK_STREAM, IPPROTO_TCP);
  if (socket == kBadSocket)
  {
    error = "cannot create a socket";
    return kBadSocket;
  }
  int one = 1;
  setsockopt(socket, IPPROTO_TCP, TCP_NODELAY, reinterpret_cast<const char*>(&one), sizeof(one));

#ifdef _WIN32
  u_long nonblocking = 1;
  ioctlsocket(socket, FIONBIO, &nonblocking);
  const int result = connect(socket, reinterpret_cast<const sockaddr*>(&address.storage),
                             address.length);
  if (result == SOCKET_ERROR)
  {
    const int code = WSAGetLastError();
    if (code != WSAEWOULDBLOCK && code != WSAEINPROGRESS && code != WSAEINVAL)
    {
      error = SocketError(code);
      CloseSocket(socket);
      return kBadSocket;
    }
    fd_set writable;
    FD_ZERO(&writable);
    FD_SET(socket, &writable);
    timeval wait{};
    wait.tv_sec = timeout;
    wait.tv_usec = 0;
    const int ready = select(0, nullptr, &writable, nullptr, &wait);
    if (ready <= 0)
    {
      error = ready == 0 ? "timeout" : "cannot wait for the connection";
      CloseSocket(socket);
      return kBadSocket;
    }
    int pending = 0;
    int length = sizeof(pending);
    getsockopt(socket, SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&pending), &length);
    if (pending != 0)
    {
      error = SocketError(pending);
      CloseSocket(socket);
      return kBadSocket;
    }
  }
  nonblocking = 0;
  ioctlsocket(socket, FIONBIO, &nonblocking);
#else
  const int flags = fcntl(socket, F_GETFL, 0);
  fcntl(socket, F_SETFL, flags | O_NONBLOCK);
  const int result = connect(socket, reinterpret_cast<const sockaddr*>(&address.storage),
                             address.length);
  if (result < 0 && errno != EINPROGRESS)
  {
    error = SocketError(errno);
    CloseSocket(socket);
    return kBadSocket;
  }
  if (result < 0)
  {
    fd_set writable;
    FD_ZERO(&writable);
    FD_SET(socket, &writable);
    timeval wait{};
    wait.tv_sec = timeout;
    const int ready = select(socket + 1, nullptr, &writable, nullptr, &wait);
    if (ready <= 0)
    {
      error = ready == 0 ? "timeout" : "cannot wait for the connection";
      CloseSocket(socket);
      return kBadSocket;
    }
    int pending = 0;
    socklen_t length = sizeof(pending);
    getsockopt(socket, SOL_SOCKET, SO_ERROR, &pending, &length);
    if (pending != 0)
    {
      error = SocketError(pending);
      CloseSocket(socket);
      return kBadSocket;
    }
  }
  fcntl(socket, F_SETFL, flags);
#endif
  SetTimeout(socket, timeout);
  return socket;
}
SocketHandle ConnectSocket(const std::string& host, int port, int timeout, std::string& error)
{
  StartupSockets();
  addrinfo hints{};
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  hints.ai_protocol = IPPROTO_TCP;
  addrinfo* found = nullptr;
  const std::string service = std::to_string(port);
  const int result = getaddrinfo(host.c_str(), service.c_str(), &hints, &found);
  if (result != 0)
  {
    error = "cannot resolve " + host;
    return kBadSocket;
  }

  std::vector<Address> addresses;
  for (int family : {AF_INET, AF_INET6})
  {
    for (addrinfo* info = found; info != nullptr; info = info->ai_next)
    {
      if (info->ai_family != family)
        continue;
      Address address;
      if (PrepareAddress(info, address))
        addresses.push_back(address);
    }
  }
  freeaddrinfo(found);
  if (addresses.empty())
  {
    error = "no address for " + host;
    return kBadSocket;
  }

  std::string last;
  for (const Address& address : addresses)
  {
    std::string reason;
    const SocketHandle socket = OpenAddress(address, timeout, reason);
    if (socket != kBadSocket)
      return socket;
    last = reason;
  }
  error = last.empty() ? "cannot connect to " + host : last;
  return kBadSocket;
}
}  // namespace

std::unique_ptr<Transport> ConnectTcp(const std::string& host, int port, int timeout,
                                      std::string& error)
{
  const SocketHandle socket = ConnectSocket(host, port, timeout, error);
  if (socket == kBadSocket)
    return nullptr;
  return std::unique_ptr<Transport>(new SocketTransport(socket));
}

namespace
{
#ifdef _WIN32
constexpr DWORD kRootStores[] = {CERT_SYSTEM_STORE_CURRENT_USER,
                                 CERT_SYSTEM_STORE_LOCAL_MACHINE};
#else
const char* const kCaBundles[] = {"/etc/ssl/certs/ca-certificates.crt",
                                  "/etc/pki/tls/certs/ca-bundle.crt",
                                  "/etc/ssl/cert.pem"};
const char* const kCaFolders[] = {"/etc/ssl/certs", "/etc/pki/tls/certs",
                                  "/system/etc/security/cacerts"};
#endif

struct CaCertificates
{
  CaCertificates() { mbedtls_x509_crt_init(&chain); }
  ~CaCertificates() { mbedtls_x509_crt_free(&chain); }
  CaCertificates(const CaCertificates&) = delete;
  CaCertificates& operator=(const CaCertificates&) = delete;
  mbedtls_x509_crt chain{};
};

void LoadSystemRoots(mbedtls_x509_crt& chain)
{
#ifdef _WIN32
  for (DWORD location : kRootStores)
  {
    HCERTSTORE store = CertOpenStore(CERT_STORE_PROV_SYSTEM_A, 0, 0,
                                     location | CERT_STORE_READONLY_FLAG, "ROOT");
    if (!store)
      continue;
    PCCERT_CONTEXT item = nullptr;
    while ((item = CertEnumCertificatesInStore(store, item)) != nullptr)
      mbedtls_x509_crt_parse_der(&chain, item->pbCertEncoded, item->cbCertEncoded);
    CertCloseStore(store, 0);
  }
#else
  for (const char* bundle : kCaBundles)
    mbedtls_x509_crt_parse_file(&chain, bundle);
  for (const char* folder : kCaFolders)
    mbedtls_x509_crt_parse_path(&chain, folder);
#endif
}

std::shared_ptr<CaCertificates> LoadCa(const std::string& file, std::string& error)
{
  static std::mutex mutex;
  static std::map<std::string, std::shared_ptr<CaCertificates>> cache;
  std::lock_guard<std::mutex> lock(mutex);
  const auto found = cache.find(file);
  if (found != cache.end())
    return found->second;
  auto ca = std::make_shared<CaCertificates>();
  LoadSystemRoots(ca->chain);
  if (!file.empty() && mbedtls_x509_crt_parse_file(&ca->chain, file.c_str()) < 0)
  {
    error = "cannot read the CA certificate file " + file;
    return nullptr;
  }
  cache[file] = ca;
  return ca;
}

void TlsDebug(void* /*context*/, int level, const char* file, int line, const char* message)
{
  if (level <= 3)
    Log(LogLevel::Warning, "tls: %s:%d %s", file, line, message);
}

std::string TlsError(int code)
{
  char text[256] = {};
  mbedtls_strerror(code, text, sizeof(text));
  return text[0] == '\0' ? "TLS error " + std::to_string(code) : std::string(text);
}

int SendCallback(void* context, const unsigned char* data, size_t size)
{
  const SocketHandle socket = static_cast<SocketHandle>(reinterpret_cast<uintptr_t>(context));
#ifdef _WIN32
  const int done =
      send(socket, reinterpret_cast<const char*>(data), static_cast<int>(size), 0);
  if (done == SOCKET_ERROR)
  {
    const int code = WSAGetLastError();
    if (code == WSAEWOULDBLOCK || code == WSAEINTR)
      return MBEDTLS_ERR_SSL_WANT_WRITE;
    return MBEDTLS_ERR_NET_SEND_FAILED;
  }
  return done;
#else
  const ssize_t done = send(socket, data, size, MSG_NOSIGNAL);
  if (done < 0)
  {
    if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
      return MBEDTLS_ERR_SSL_WANT_WRITE;
    return MBEDTLS_ERR_NET_SEND_FAILED;
  }
  return static_cast<int>(done);
#endif
}

int RecvCallback(void* context, unsigned char* data, size_t size)
{
  const SocketHandle socket = static_cast<SocketHandle>(reinterpret_cast<uintptr_t>(context));
#ifdef _WIN32
  const int got = recv(socket, reinterpret_cast<char*>(data), static_cast<int>(size), 0);
  if (got == SOCKET_ERROR)
  {
    const int code = WSAGetLastError();
    if (code == WSAEWOULDBLOCK || code == WSAEINTR)
      return MBEDTLS_ERR_SSL_WANT_READ;
    return MBEDTLS_ERR_NET_RECV_FAILED;
  }
  return got;
#else
  const ssize_t got = recv(socket, data, size, 0);
  if (got < 0)
  {
    if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
      return MBEDTLS_ERR_SSL_WANT_READ;
    return MBEDTLS_ERR_NET_RECV_FAILED;
  }
  return static_cast<int>(got);
#endif
}

class TlsTransport : public Transport
{
public:
  TlsTransport(SocketHandle socket, std::string host, const std::string& cacert,
               std::string& error)
      : socket_(socket), host_(std::move(host))
  {
    mbedtls_ssl_init(&ssl_);
    mbedtls_ssl_config_init(&conf_);
    mbedtls_ctr_drbg_init(&drbg_);
    mbedtls_entropy_init(&entropy_);

    ca_ = LoadCa(cacert, error);
    if (!ca_)
      return;

    static const unsigned char seed[] = "tmdbusenet";
    int result = mbedtls_ctr_drbg_seed(&drbg_, mbedtls_entropy_func, &entropy_, seed,
                                       sizeof(seed) - 1);
    if (result != 0)
    {
      error = "cannot seed TLS: " + TlsError(result);
      return;
    }
    result = mbedtls_ssl_config_defaults(&conf_, MBEDTLS_SSL_IS_CLIENT,
                                         MBEDTLS_SSL_TRANSPORT_STREAM,
                                         MBEDTLS_SSL_PRESET_DEFAULT);
    if (result != 0)
    {
      error = "cannot prepare TLS: " + TlsError(result);
      return;
    }
    mbedtls_ssl_conf_min_tls_version(&conf_, MBEDTLS_SSL_VERSION_TLS1_2);
    mbedtls_ssl_conf_authmode(&conf_, MBEDTLS_SSL_VERIFY_REQUIRED);
    mbedtls_ssl_conf_rng(&conf_, mbedtls_ctr_drbg_random, &drbg_);
    mbedtls_ssl_conf_ca_chain(&conf_, &ca_->chain, nullptr);
    if (std::getenv("TMDBUSENET_TLS_DEBUG"))
    {
      mbedtls_debug_set_threshold(4);
      mbedtls_ssl_conf_dbg(&conf_, TlsDebug, nullptr);
    }

    result = mbedtls_ssl_setup(&ssl_, &conf_);
    if (result != 0)
    {
      error = "cannot prepare TLS: " + TlsError(result);
      return;
    }
    result = mbedtls_ssl_set_hostname(&ssl_, host_.c_str());
    if (result != 0)
    {
      error = "cannot set the TLS server name " + host_ + ": " + TlsError(result);
      return;
    }
    mbedtls_ssl_set_bio(&ssl_, reinterpret_cast<void*>(static_cast<uintptr_t>(socket_.load())),
                        SendCallback, RecvCallback, nullptr);

    result = mbedtls_ssl_handshake(&ssl_);
    while (result == MBEDTLS_ERR_SSL_WANT_READ || result == MBEDTLS_ERR_SSL_WANT_WRITE)
      result = mbedtls_ssl_handshake(&ssl_);
    if (result != 0)
    {
      error = "TLS with " + host_ + " failed: " + TlsError(result) + VerifyInfo();
      return;
    }
    ready_.store(true);
  }

  ~TlsTransport() override
  {
    CloseSocket(socket_.exchange(kBadSocket));
    mbedtls_ssl_free(&ssl_);
    mbedtls_ssl_config_free(&conf_);
    mbedtls_ctr_drbg_free(&drbg_);
    mbedtls_entropy_free(&entropy_);
  }

  bool Ready() const { return ready_.load(); }

  int Recv(void* data, size_t size, std::string& error) override
  {
    if (!ready_.load())
    {
      error = "TLS is not ready";
      return -1;
    }
    for (;;)
    {
      const int got = mbedtls_ssl_read(&ssl_, static_cast<unsigned char*>(data), size);
      if (got >= 0)
        return got;
      if (got == MBEDTLS_ERR_SSL_WANT_READ || got == MBEDTLS_ERR_SSL_WANT_WRITE)
        continue;
      if (got == MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY)
        return 0;
      error = TlsError(got);
      return -1;
    }
  }

  bool SendAll(const void* data, size_t size, std::string& error) override
  {
    if (!ready_.load())
    {
      error = "TLS is not ready";
      return false;
    }
    const auto* bytes = static_cast<const unsigned char*>(data);
    size_t sent = 0;
    while (sent < size)
    {
      const int done = mbedtls_ssl_write(&ssl_, bytes + sent, size - sent);
      if (done > 0)
      {
        sent += static_cast<size_t>(done);
        continue;
      }
      if (done == MBEDTLS_ERR_SSL_WANT_READ || done == MBEDTLS_ERR_SSL_WANT_WRITE)
        continue;
      error = TlsError(done);
      return false;
    }
    return true;
  }

  void Close() override
  {
    ready_.store(false);
    ShutdownSocket(socket_.load());
  }

private:
  std::string VerifyInfo() const
  {
    const uint32_t flags = mbedtls_ssl_get_verify_result(&ssl_);
    if (flags == 0 || flags == 0xFFFFFFFFu)
      return std::string();
    char info[512] = {};
    mbedtls_x509_crt_verify_info(info, sizeof(info), "", flags);
    std::string text(info);
    for (char& value : text)
      if (value == '\r' || value == '\n')
        value = ' ';
    while (!text.empty() && text.back() == ' ')
      text.pop_back();
    return text.empty() ? std::string() : " (" + text + ")";
  }

  std::atomic<SocketHandle> socket_{kBadSocket};
  std::string host_;
  std::shared_ptr<CaCertificates> ca_;
  mbedtls_ssl_context ssl_{};
  mbedtls_ssl_config conf_{};
  mbedtls_ctr_drbg_context drbg_{};
  mbedtls_entropy_context entropy_{};
  std::atomic<bool> ready_{false};
};
}  // namespace

std::unique_ptr<Transport> ConnectTls(const std::string& host, int port, int timeout,
                                      const std::string& cacert, std::string& error)
{
  static std::once_flag crypto_once;
  static psa_status_t crypto_status = PSA_ERROR_GENERIC_ERROR;
  std::call_once(crypto_once, []() { crypto_status = psa_crypto_init(); });
  if (crypto_status != PSA_SUCCESS)
  {
    error = "cannot initialize the TLS crypto library";
    return nullptr;
  }

  const SocketHandle socket = ConnectSocket(host, port, timeout, error);
  if (socket == kBadSocket)
    return nullptr;
  auto tls = std::unique_ptr<TlsTransport>(new TlsTransport(socket, host, cacert, error));
  if (!tls->Ready())
    return nullptr;
  return std::unique_ptr<Transport>(tls.release());
}

}  // namespace engine
