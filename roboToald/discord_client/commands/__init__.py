from roboToald.discord_client.commands import cmd_random
from roboToald.discord_client.commands import cmd_batphone
from roboToald.discord_client.commands import cmd_timer
from roboToald.discord_client.commands import cmd_raidtarget
from roboToald.discord_client.commands import cmd_ds
from roboToald.discord_client.commands import cmd_ds_data

BUTTON_LISTENERS = {}
for module in (cmd_random, cmd_batphone, cmd_timer, cmd_raidtarget, cmd_ds,
               cmd_ds_data):
    try:
        bls = module.BUTTON_LISTENERS
        for bl, func in bls.items():
            if bl in BUTTON_LISTENERS:
                raise KeyError(f"Duplicate key found: {bl}")
            BUTTON_LISTENERS[bl] = func
    except AttributeError:
        pass
