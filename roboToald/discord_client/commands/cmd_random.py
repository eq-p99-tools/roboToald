import random as pyrandom

import disnake
from disnake.ext import commands

from roboToald.discord_client import base


@base.DISCORD_CLIENT.slash_command(description="Random Number Generator")
async def random(inter: disnake.ApplicationCommandInteraction,
                 end: int = commands.Param(ge=1, default=100),
                 start: int = commands.Param(ge=0, default=0)):
    print("Received random number request, num1: %s; num2: %s" % (start, end))

    if start > end:
        await inter.response.send_message(
            f"The supplied range is invalid: start (`{start}`) is greater "
            f"than end (`{end}`). You're better, do better.",
            ephemeral=True)
        return

    result = pyrandom.randint(start, end)
    await inter.response.send_message(
        f"\*\*A Magic Die is rolled by {inter.user.display_name.split()[0]}.\n"
        f"\*\*It could have been any number from `{start}` to `{end}`, "
        f"but this time it turned up a `{result}`.")
