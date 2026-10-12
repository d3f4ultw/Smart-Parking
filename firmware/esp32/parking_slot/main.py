from api_client import ApiClient
from config import (
    API_BASE_URL,
    API_DISABLED_RETRY_MS,
    API_RETRY_MS,
    NETWORK_RECONNECT_MS,
    PARKING_SLOTS,
    POLL_INTERVAL_MS,
)
from parking_controller import ParkingController
from parking_sensor import ParkingSensor
from secrets import (  # pyright: ignore[reportAttributeAccessIssue]
    ESP32_BEARER_TOKEN,
    PASSWORD,
    SSID,
)
from wifi_manager import WifiManager

wifi_manager = WifiManager(
    SSID,
    PASSWORD,
    NETWORK_RECONNECT_MS,
)
wifi_manager.start()

sensors = [
    ParkingSensor(cajon_id, gpio_pin)
    for cajon_id, gpio_pin in PARKING_SLOTS
]

api_client = ApiClient(API_BASE_URL, ESP32_BEARER_TOKEN)

controller = ParkingController(
    sensors,
    POLL_INTERVAL_MS,
    api_client,
    wifi_manager=wifi_manager,
    api_retry_ms=API_RETRY_MS,
    api_disabled_retry_ms=API_DISABLED_RETRY_MS,
)
controller.monitor()
