# The browser adapter (#544, ADR-0021). One source set, two builds:
#   native:      cmake -S web -B web/build && cmake --build web/build
#   WebAssembly: emcmake cmake -S web -B web/build-wasm && cmake --build web/build-wasm
# Both produce ahn-web-trace (the parity runner); the WASM build also produces
# the ES module the learn site loads (anthocnet.js + anthocnet.wasm).
cmake_minimum_required(VERSION 3.20)
project(anthocnet_web LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
add_compile_options(-Wall -Wextra)
# Parity: no floating-point contraction (an FMA on one side would change the
# last bit), no fast-math anywhere.
add_compile_options(-ffp-contract=off)

set(CORE ${CMAKE_CURRENT_SOURCE_DIR}/../core)

# AntHocNet's core/ builds on swarm-core's core/ (swarm-routing/ns3-swarm-core#14,
# from its slice S1). This build compiles the same core sources, so it gets
# swarm-core the way AntHocNet's core/CMakeLists.txt does and links its
# swarm::core target, under the directory options above (-ffp-contract=off
# reaches swarm-core's sources too):
#  - a release lock, ../swarm-core.lock (swarm-routing/ns3-swarm-core#134):
#    the release tarball by URL, checked against the lock's SHA256;
#  - else a commit pin, set(SWARM_CORE_REF "<sha>") in ../core/CMakeLists.txt;
#  - else nothing (an AntHocNet commit before S1 builds as before).
# SWARM_CORE_DIR=<swarm-core checkout>/core builds against a local copy (offline).
set(SWARM_CORE_DIR "" CACHE PATH "swarm-core's core/ directory; empty: AntHocNet's lock or pin")
set(_ahn_lock ${CMAKE_CURRENT_SOURCE_DIR}/../swarm-core.lock)
file(STRINGS ${CORE}/CMakeLists.txt _ahn_swarm_core_ref
     REGEX "^[ \t]*set\\(SWARM_CORE_REF \"[0-9a-f]+\"")
# Re-run the configure step when the lock or the pin moves (file(STRINGS) alone does not).
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${CORE}/CMakeLists.txt)
set(_ahn_swarm_core OFF)
if(SWARM_CORE_DIR)
  if(NOT EXISTS "${SWARM_CORE_DIR}/swarm-ports.h")
    message(FATAL_ERROR "SWARM_CORE_DIR=${SWARM_CORE_DIR} is not swarm-core's core/ directory")
  endif()
  add_subdirectory(${SWARM_CORE_DIR} ${CMAKE_CURRENT_BINARY_DIR}/swarm-core)
  set(_ahn_swarm_core ON)
elseif(EXISTS ${_ahn_lock})
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${_ahn_lock})
  file(STRINGS ${_ahn_lock} _ahn_lock_lines REGEX "^SWARM_CORE_[A-Z0-9_]+=")
  foreach(_kv IN LISTS _ahn_lock_lines)
    string(REGEX MATCH "^([A-Z0-9_]+)=(.*)$" _m "${_kv}")
    set(_LOCK_${CMAKE_MATCH_1} "${CMAKE_MATCH_2}")
  endforeach()
  foreach(_key REPO TAG ASSET SHA256)
    if(NOT _LOCK_SWARM_CORE_${_key})
      message(FATAL_ERROR "swarm-core.lock: no SWARM_CORE_${_key}")
    endif()
  endforeach()
  set(_ahn_timestamp)
  if(CMAKE_VERSION VERSION_GREATER_EQUAL 3.24)
    set(_ahn_timestamp DOWNLOAD_EXTRACT_TIMESTAMP FALSE)
  endif()
  include(FetchContent)
  FetchContent_Declare(swarm_core_src
    URL https://github.com/${_LOCK_SWARM_CORE_REPO}/releases/download/${_LOCK_SWARM_CORE_TAG}/${_LOCK_SWARM_CORE_ASSET}
    URL_HASH SHA256=${_LOCK_SWARM_CORE_SHA256}
    ${_ahn_timestamp}
    SOURCE_SUBDIR core)
  FetchContent_MakeAvailable(swarm_core_src)
  set(_ahn_swarm_core ON)
elseif(_ahn_swarm_core_ref)
  string(REGEX MATCH "[0-9a-f]+\"" _ahn_ref "${_ahn_swarm_core_ref}")
  string(REPLACE "\"" "" _ahn_ref "${_ahn_ref}")
  include(FetchContent)
  FetchContent_Declare(swarm_core_src
    GIT_REPOSITORY https://github.com/swarm-routing/swarm-adapter-ns3.git
    GIT_TAG ${_ahn_ref}
    SOURCE_SUBDIR core)
  FetchContent_MakeAvailable(swarm_core_src)
  set(_ahn_swarm_core ON)
endif()

add_library(ahn_web STATIC
  ${CORE}/src/pheromone_table.cpp
  ${CORE}/src/pheromone_engine.cpp
  ${CORE}/src/ant_history.cpp
  ${CORE}/src/ant_message_codec.cpp
  ${CORE}/src/ant_router_logic.cpp
  ${CORE}/src/link_metric_registry.cpp
  src/sim.cpp
  src/scenarios.cpp)
target_include_directories(ahn_web PUBLIC ${CORE}/include include)
if(_ahn_swarm_core)
  target_link_libraries(ahn_web PUBLIC swarm::core)
endif()

add_executable(ahn-web-trace src/trace_main.cpp)
target_link_libraries(ahn-web-trace ahn_web)
add_executable(ahn-web-features test/features.cpp)
target_link_libraries(ahn-web-features ahn_web)

if(EMSCRIPTEN)
  target_link_options(ahn-web-trace PRIVATE -sENVIRONMENT=node -sALLOW_MEMORY_GROWTH=1
                      -sNODERAWFS=1)
  target_link_options(ahn-web-features PRIVATE -sENVIRONMENT=node)
  add_executable(anthocnet src/bindings.cpp)
  target_link_libraries(anthocnet ahn_web)
  target_link_options(anthocnet PRIVATE --bind -sMODULARIZE=1 -sEXPORT_ES6=1
                      -sEXPORT_NAME=createAntHocNet -sENVIRONMENT=web,worker,node
                      -sALLOW_MEMORY_GROWTH=1 -sFILESYSTEM=0)
endif()
