idf_component_register(
    SRCS
        "main.c"
        "rx_task.c"
        "render_task.c"
        "input_task.c"
        "watchdog_task.c"
    INCLUDE_DIRS
        "."
    REQUIRES
        nvs_flash driver esp_timer
        volthium_lib
)
