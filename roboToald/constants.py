import zoneinfo
import enum

SQUADCAST_WEBHOOK_URL = (
    "https://support.squadcast.com/docs/apiv2"
    "#how-to-configure-incident-webhook")

TEST_EMOJI = "🧪"
DELETE_EMOJI = "🗑"
CLEAR_EMOJI = "⏱"

POINTS_PER_MINUTE = 1
OFFHOURS_MULTIPLIER = 2
CONTESTED_MULTIPLIER = 3

# Times are Minutes from Midnight assuming EST
OFFHOURS_START = -2 * 60
OFFHOURS_END = 6 * 60
OFFHOURS_ZONE = zoneinfo.ZoneInfo("America/New_York")


class Event(enum.Enum):
    IN = 'IN',
    OUT = 'OUT'
    COMP_START = "COMP_START"
    COMP_END = "COMP_END"
