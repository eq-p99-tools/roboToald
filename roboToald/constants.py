import enum

from dateutil import tz

SQUADCAST_WEBHOOK_URL = (
    "https://support.squadcast.com/docs/apiv2"
    "#how-to-configure-incident-webhook")

TEST_EMOJI = "🧪"
DELETE_EMOJI = "🗑"
CLEAR_EMOJI = "⏱"

TIMEZONES = {
    "ET": tz.gettz("US/Eastern"),
    "EST": tz.gettz("US/Eastern"),
    "EDT": tz.gettz("US/Eastern"),
    "CT": tz.gettz("US/Central"),
    "CST": tz.gettz("US/Central"),
    "CDT": tz.gettz("US/Central"),
    "PT": tz.gettz("US/Pacific"),
    "PST": tz.gettz("US/Pacific"),
    "PDT": tz.gettz("US/Pacific"),
}


class Event(enum.Enum):
    IN = 'IN'
    OUT = 'OUT'
    COMP_START = "COMP_START"
    COMP_END = "COMP_END"
