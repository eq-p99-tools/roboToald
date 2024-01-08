import enum

SQUADCAST_WEBHOOK_URL = (
    "https://support.squadcast.com/docs/apiv2"
    "#how-to-configure-incident-webhook")

TEST_EMOJI = "🧪"
DELETE_EMOJI = "🗑"
CLEAR_EMOJI = "⏱"


class Event(enum.Enum):
    IN = 'IN'
    OUT = 'OUT'
    COMP_START = "COMP_START"
    COMP_END = "COMP_END"
