# ESP-IDF component definition for volthium_lib.
#
# This file is only consulted when the surrounding code is being built
# under ESP-IDF (which adds EXTRA_COMPONENT_DIRS to find us). The
# standalone host-side Makefile (the sibling file) is still used for
# the dev-machine test programs.

idf_component_register(
    SRCS
        "wire_protocol.c"
        "estimator.c"
    INCLUDE_DIRS
        "."
    REQUIRES
        # No ESP-IDF specific requires — this lib is portable.
)
