from roboToald import config

from roboToald.discord_client.commands import cmd_random
from roboToald.discord_client.commands import cmd_batphone
from roboToald.discord_client.commands import cmd_timer
from roboToald.discord_client.commands import cmd_raidtarget
from roboToald.discord_client.commands import cmd_ds
from roboToald.discord_client.commands import cmd_ds_data
from roboToald.discord_client.commands import cmd_sso

if config.EQDKP_SETTINGS:
    from roboToald.discord_client.commands import cmd_lookup  # noqa: F401

if config.guilds_for_command("raid"):
    from roboToald.discord_client.commands import cmd_event  # noqa: F401
    from roboToald.discord_client.commands import cmd_rte  # noqa: F401
    from roboToald.discord_client.commands import cmd_loot  # noqa: F401
    from roboToald.discord_client.commands import cmd_history  # noqa: F401

BUTTON_LISTENERS = {}
_MODULES = (
    cmd_random, cmd_batphone, cmd_timer,
    cmd_raidtarget, cmd_ds, cmd_ds_data, cmd_sso,
)
for module in _MODULES:
    try:
        bls = module.BUTTON_LISTENERS
        for bl, func in bls.items():
            if bl in BUTTON_LISTENERS:
                raise KeyError(f"Duplicate key found: {bl}")
            BUTTON_LISTENERS[bl] = func
    except AttributeError:
        pass
