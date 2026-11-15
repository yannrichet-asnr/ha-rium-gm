"""Constantes de l'intégration Rium GM (USB)."""
DOMAIN = "rium_gm"

# Identifiants USB et paramètres série repris d'OpenRadiation
# (src/app/states/devices/usb/device-rium*.ts). VID 03EB = Atmel/Microchip :
# identifiant générique, d'autres appareils Atmel peuvent le partager.
USB_VID = 0x03EB
USB_PID = 0x2404
BAUDRATE = 115200

CONF_PORT = "port"
CONF_WINDOW = "window"            # fenêtre glissante de calcul du taux (s)
CONF_SCAN_INTERVAL = "scan_interval"  # période de publication des états (s)
DEFAULT_WINDOW = 120
DEFAULT_SCAN_INTERVAL = 10

RECONNECT_DELAY = 10  # s

# OpenRadiation (options, section "openradiation")
CONF_OPENRADIATION = "openradiation"
CONF_OR_ENABLED = "enabled"
CONF_OR_API_KEY = "api_key"
CONF_OR_PRODUCTION = "production"
CONF_OR_LATITUDE = "latitude"
CONF_OR_LONGITUDE = "longitude"
CONF_OR_ENVIRONMENT = "environment"
CONF_OR_HEIGHT = "height"
CONF_OR_PERIOD = "period"
CONF_OR_USER_ID = "user_id"
CONF_OR_USER_PWD = "user_pwd"
DEFAULT_OR_PERIOD = 900
VERSION = "0.3.0"
