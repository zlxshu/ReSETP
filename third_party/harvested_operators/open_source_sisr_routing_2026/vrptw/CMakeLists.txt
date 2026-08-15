cmake_minimum_required(VERSION 3.10)

project(VRP)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# Profiler
# set(CMAKE_CXX_FLAGS "-g -gdwarf-2")

set(CMAKE_CXX_FLAGS "-O3")

set(CMAKE_CXX_COMPILER g++)

file(GLOB SOURCES "src/*.cpp" "lib/*.cpp" "lib/*.hpp")

add_executable(solver ${SOURCES})
