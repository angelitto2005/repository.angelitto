cmake_minimum_required(VERSION 3.20)
project(vfs.tmdbusenet CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

set(KODI_DEVKIT "${CMAKE_CURRENT_SOURCE_DIR}/vendor/xbmc/xbmc/addons/kodi-dev-kit/include" CACHE PATH "Kodi devkit include directory")

set(ENABLE_PROGRAMS OFF CACHE BOOL "" FORCE)
set(ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(MBEDTLS_FATAL_WARNINGS OFF CACHE BOOL "" FORCE)
set(GEN_FILES OFF CACHE BOOL "" FORCE)
set(USE_SHARED_MBEDTLS_LIBRARY OFF CACHE BOOL "" FORCE)
set(USE_STATIC_MBEDTLS_LIBRARY ON CACHE BOOL "" FORCE)
add_subdirectory(vendor/mbedtls EXCLUDE_FROM_ALL)

add_library(tmdbusenet_core STATIC
  src/engine/common.cpp
  src/engine/plan.cpp
  src/engine/yenc.cpp
  src/engine/transport.cpp
  src/engine/nntp.cpp
  src/engine/stream.cpp)
target_include_directories(tmdbusenet_core PUBLIC
  "${CMAKE_CURRENT_SOURCE_DIR}/src"
  "${CMAKE_CURRENT_SOURCE_DIR}/vendor/mbedtls/include")
target_link_libraries(tmdbusenet_core PUBLIC mbedtls mbedx509 mbedcrypto)
if(WIN32)
  target_link_libraries(tmdbusenet_core PUBLIC ws2_32 crypt32)
elseif(ANDROID)
  target_link_libraries(tmdbusenet_core PUBLIC log)
endif()

add_library(vfs.tmdbusenet SHARED src/addon.cpp)
target_include_directories(vfs.tmdbusenet PRIVATE "${KODI_DEVKIT}")
if(ANDROID)
  target_compile_definitions(vfs.tmdbusenet PRIVATE
    BUILD_KODI_ADDON
    TARGET_ANDROID
    TARGET_POSIX
    ADDON_GLOBAL_VERSION_MAIN_USED
    ADDON_GLOBAL_VERSION_GENERAL_USED
    ADDON_GLOBAL_VERSION_FILESYSTEM_USED
    ADDON_INSTANCE_VERSION_VFS_USED)
  set(ADDON_PREFIX "lib")
  set(ADDON_SUFFIX ".so")
else()
  target_compile_definitions(vfs.tmdbusenet PRIVATE
    BUILD_KODI_ADDON
    TARGET_WINDOWS
    ADDON_GLOBAL_VERSION_MAIN_USED
    ADDON_GLOBAL_VERSION_GENERAL_USED
    ADDON_GLOBAL_VERSION_FILESYSTEM_USED
    ADDON_INSTANCE_VERSION_VFS_USED)
  set(ADDON_PREFIX "")
  set(ADDON_SUFFIX ".dll")
endif()
set_target_properties(vfs.tmdbusenet PROPERTIES
  PREFIX "${ADDON_PREFIX}"
  OUTPUT_NAME "vfs.tmdbm"
  SUFFIX "${ADDON_SUFFIX}"
  CXX_VISIBILITY_PRESET hidden
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/dist/vfs.tmdbm"
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/dist/vfs.tmdbm")
target_link_libraries(vfs.tmdbusenet PRIVATE tmdbusenet_core)
if(WIN32)
  target_link_options(vfs.tmdbusenet PRIVATE -static -static-libgcc -static-libstdc++ -s)
elseif(ANDROID)
  target_link_options(vfs.tmdbusenet PRIVATE -Wl,-s)
endif()

add_custom_command(TARGET vfs.tmdbusenet POST_BUILD
  COMMAND "${CMAKE_COMMAND}" -E copy_if_different
          "${CMAKE_CURRENT_SOURCE_DIR}/addon.xml"
          "$<TARGET_FILE_DIR:vfs.tmdbusenet>/addon.xml"
  COMMAND "${CMAKE_COMMAND}" -E copy_if_different
          "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE.txt"
          "$<TARGET_FILE_DIR:vfs.tmdbusenet>/LICENSE.txt"
  COMMAND "${CMAKE_COMMAND}" -E copy_if_different
          "${CMAKE_CURRENT_SOURCE_DIR}/THIRD-PARTY-NOTICES.txt"
          "$<TARGET_FILE_DIR:vfs.tmdbusenet>/THIRD-PARTY-NOTICES.txt"
  COMMAND "${CMAKE_COMMAND}" -E copy_directory
          "${CMAKE_CURRENT_SOURCE_DIR}/licenses"
          "$<TARGET_FILE_DIR:vfs.tmdbusenet>/licenses")

add_executable(stream_test tools/stream_test.cpp)
target_link_libraries(stream_test PRIVATE tmdbusenet_core)
if(WIN32)
  target_link_options(stream_test PRIVATE -static -static-libgcc -static-libstdc++)
endif()
set_target_properties(stream_test PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/dist/tools")
