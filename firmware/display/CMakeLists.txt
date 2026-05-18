# Top-level CMakeLists for the kitchen display-side ESP-IDF project.
#
# Build:
#     cd firmware/display
#     idf.py set-target esp32s3
#     idf.py build
#     idf.py -p /dev/cu.usbserial-XXXX flash monitor

cmake_minimum_required(VERSION 3.16)

# Make volthium_lib (sibling component in firmware/common/) visible.
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_SOURCE_DIR}/../common")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(volthium_display)
