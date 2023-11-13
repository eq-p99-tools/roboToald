import asyncio
import datetime
import time

import disnake
from disnake.ext import commands

from roboToald import config
from roboToald.db.models import subscription as sub_model
from roboToald.discord_client import base
from roboToald.raidtargets import rt_data

MAX_AC_RESULTS = 25


@base.DISCORD_CLIENT.slash_command(description="Raid Target commands")
async def raidtarget(inter: disnake.ApplicationCommandInteraction):
    pass


def autocomplete_raid_target(
        inter: disnake.ApplicationCommandInteraction,
        user_input: str):
    return [target_name for target_name in rt_data.RaidTargets.get_all_names()
            if user_input.lower() in target_name.lower()][:MAX_AC_RESULTS]


def autocomplete_existing_subscription(
        inter: disnake.ApplicationCommandInteraction,
        user_input: str):
    subs = sub_model.get_subscriptions_for_user(inter.user.id)
    return [sub.target for sub in subs]


def is_user_authorized(user_id: int, guild_id: int, role_id: int) -> bool:
    user = base.DISCORD_CLIENT.get_guild(guild_id).get_member(user_id)
    if user:
        role = user.get_role(role_id)
        if role:
            return True
    return False


@raidtarget.sub_command(
    description="Subscribe to a raid target timer", name="subscribe")
async def subscribe(
        inter: disnake.ApplicationCommandInteraction,
        target: str = commands.Param(
            autocomplete=autocomplete_raid_target,
            description="The name of the raid target")
):
    if is_user_authorized(
            user_id=inter.user.id,
            guild_id=inter.guild_id,
            role_id=get_member_role(inter.guild_id)):
        sub_db = sub_model.Subscription(
            user_id=inter.user.id,
            target=target,
            expiry=int(
                time.time() + datetime.timedelta(days=30).total_seconds()),
            last_notified=0,
            guild_id=inter.guild_id
        )
        try:
            sub_db.store()
            message = f"Subscribed to `{target}`."
        except:
            message = (
                f"Failed to subscribe to `{target}`. Either this subscription "
                f"already exists, or something went *horribly wrong* "
                f"and everything is about to be on fire.")
    else:
        message = "You are not authorized to subscribe to raid _targets."

    await inter.send(
        content=message,
        ephemeral=True
    )


@raidtarget.sub_command(
    description="Unsubscribe from a raid target timer", name="unsubscribe")
async def unsubscribe(
        inter: disnake.ApplicationCommandInteraction,
        target: str = commands.Param(
            autocomplete=autocomplete_existing_subscription,
            description="The name of the raid target")
):
    try:
        sub_model.delete_subscription(user_id=inter.user.id, target=target)
        message = f"Unsubscribed from `{target}`."
    except:
        message = (
            f"Failed to unsubscribe from `{target}`. Either this subscription "
            f"doesn't exist, or something went *horribly wrong* "
            f"and everything is about to be on fire.")

    await inter.send(
        content=message,
        ephemeral=True
    )


@raidtarget.sub_command(
    description="Unsubscribe from a raid target timer", name="subscriptions")
async def subscriptions(inter: disnake.ApplicationCommandInteraction):
    user_subs = sub_model.get_subscriptions_for_user(inter.user.id)

    embeds = []
    for sub in user_subs:
        embeds.append(make_subscription_embed(sub))

    dm = None
    s = 's' if len(embeds) > 1 else ''
    if embeds:
        dm = await inter.user.send(content=f"Subscription{s}:")
    for embed in embeds:
        await inter.user.send(
            embed=embed,
            components=[
                disnake.ui.Button(
                    label="Unsubscribe",
                    style=disnake.ButtonStyle.danger,
                    custom_id="unsubscribe"),
                disnake.ui.Button(
                    label="Refresh",
                    style=disnake.ButtonStyle.success,
                    custom_id="refresh"),
            ]
        )

    if embeds:
        message = f"Sent {len(embeds)} subscription{s} via DM: {dm.jump_url}"
    else:
        message = "No active subscriptions found."
    await inter.send(
        content=message,
        ephemeral=True
    )


def make_subscription_embed(sub_obj: sub_model.Subscription) -> disnake.Embed:
    return disnake.Embed(
        title=sub_obj.target,
        description=f"Expires <t:{sub_obj.expiry}:R>"
    )


def get_member_role(guild_id: int) -> int:
    return config.GUILD_SETTINGS[guild_id].get('member_role')


async def refresh_listener(inter: disnake.MessageInteraction):
    target = inter.message.embeds[0].title
    user_id = inter.user.id
    new_sub = sub_model.refresh_subscription(user_id=user_id, target=target)
    if new_sub:
        await inter.message.edit(
            content="Refreshed.",
            embeds=[make_subscription_embed(sub_obj=new_sub)]
        )
    await inter.response.defer()


async def unsubscribe_listener(inter: disnake.MessageInteraction):
    target = inter.message.embeds[0].title
    user_id = inter.user.id
    deleted = sub_model.delete_subscription(user_id=user_id, target=target)
    if deleted:
        await inter.message.edit(
            content=f"Unsubscribed from target `{target}`.",
            embeds=[],
            components=[]
        )
    await inter.response.defer()


async def announce_subscriptions():
    # print("Running subscription notification task.")
    sub_model.clean_expired_subscriptions()
    subs_for_notify = sub_model.get_subscriptions_for_notification()
    sub_map = {}
    for sub in subs_for_notify:
        if sub.target not in sub_map:
            sub_map[sub.target] = [sub]
        else:
            sub_map[sub.target].append(sub)

    now = time.time()
    messages = []
    for target in rt_data.RaidTargets.get_targets():
        active_window = target.get_active_window(now)
        if not active_window:
            continue
        status = active_window.get_status(now)
        if (status <= rt_data.RaidWindowStatus.SOON and
                (active_window.get_time_until(now) <
                 datetime.timedelta(minutes=30))):
            past_tense = status == rt_data.RaidWindowStatus.NOW
            message = (
                f":boom:**Target Notification**:boom: `{target.name}` "
                f"enter{'ed' if past_tense else 'ing'} window "
                f"<t:{active_window.start}:R>.")
            if past_tense:
                percent = active_window.get_percent_elapsed(now)
                time_left = active_window.duration * (1 - percent)
                time_left = datetime.timedelta(
                    seconds=int(time_left.total_seconds()))
                message += (
                    f" Window is {percent * 100:.2f}% complete with "
                    f"{time_left} remaining.")
            for sub in sub_map.get(target.name, []):
                if is_user_authorized(
                        user_id=sub.user_id, guild_id=sub.guild_id,
                        role_id=get_member_role(sub.guild_id)):
                    user = base.DISCORD_CLIENT.get_user(sub.user_id)
                    if user:
                        messages.append(user.send(message))
                        sub_model.mark_subscription_sent(
                            sub.user_id, target.name)
                    else:
                        print(f"Could not load user for DM: {sub.user_id}")
                else:
                    print(f"User `{sub.user_id}` did not have the required "
                          f"role, removing watch `{target.name}`.")
                    sub_model.delete_subscription(sub.user_id, target.name)

    await asyncio.gather(*messages)
    print(f"Sent {len(messages)} subscription notifications.")


BUTTON_LISTENERS = {
    'unsubscribe': unsubscribe_listener,
    'refresh': refresh_listener
}
