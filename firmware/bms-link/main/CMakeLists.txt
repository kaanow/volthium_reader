idf_component_register(
    SRCS
        "main.c"
        "ble_task.c"
        "tx_task.c"
        "power_task.c"
        "adc_task.c"
    INCLUDE_DIRS
        "."
    REQUIRES
        # ESP-IDF components we use
        bt nvs_flash driver esp_timer
        # Our shared library (in firmware/common/volthium_lib)
        volthium_lib
)
