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
            description="The name of the raid target"),
        lead_time_minutes: int = commands.Param(
            default=30,
            description="Number of minutes before the window to send the "
                        "notification (additive with seconds)"),
        lead_time_seconds: int = commands.Param(
            default=0,
            description="Number of seconds before the window to send the "
                        "notification (additive with minutes, which defaults "
                        "to 30)")
):
    lead_time = int(lead_time_minutes * 60 + lead_time_seconds)
    if is_user_authorized(
            user_id=inter.user.id,
            guild_id=inter.guild_id,
            role_id=get_member_role(inter.guild_id)):
        sub_db = sub_model.Subscription(
            user_id=inter.user.id,
            target=target,
            expiry=int(
                time.time() + datetime.timedelta(days=30).total_seconds()),
            guild_id=inter.guild_id,
            lead_time=lead_time
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
    last_notified = (f"<t:{sub_obj.last_notified}:R>"
                     if sub_obj.last_notified else "Never")
    embed = disnake.Embed(
        title=sub_obj.target
    )
    embed.add_field("Lead Time", "{:0>8}".format(
        str(datetime.timedelta(seconds=sub_obj.lead_time))))
    embed.add_field("Last Notification", last_notified)
    embed.add_field("Expires", f"<t:{sub_obj.expiry}:R>")
    return embed


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


def make_announce_embed(
        active_window: rt_data.RaidWindow) -> disnake.Embed:
    embed = disnake.Embed()
    target = active_window.target
    embed.title = f":boom:** {target.name} **:boom:"
    embed.add_field("Start", f"<t:{active_window.start}:R>")
    embed.add_field("End", f"<t:{active_window.end}:R>")
    next_window = active_window.get_next()
    if next_window:
        embed.add_field("Next (estimated)", f"<t:{next_window.start}:R>")
    return embed


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
    raid_targets = rt_data.RaidTargets.get_targets()
    for target in raid_targets:
        if target.name not in sub_map:
            continue
        active_window = target.get_active_window(now)
        if not active_window:
            continue
        time_until = active_window.get_time_until(now)
        embed = make_announce_embed(active_window)
        for sub in sub_map[target.name]:
            within_lead = time_until <= datetime.timedelta(seconds=sub.lead_time)
            already_notified = sub.last_window_start == active_window.start
            if within_lead and not already_notified:
                if is_user_authorized(
                        user_id=sub.user_id, guild_id=sub.guild_id,
                        role_id=get_member_role(sub.guild_id)):
                    user = base.DISCORD_CLIENT.get_user(sub.user_id)
                    if user:
                        messages.append(user.send(embed=embed))
                        sub_model.mark_subscription_sent(
                            sub.user_id, target.name,
                            start_time=active_window.start
                        )
                    else:
                        print(f"Could not load user for DM: {sub.user_id}")
                else:
                    print(f"User `{sub.user_id}` did not have the required "
                          f"role, removing watch `{target.name}`.")
                    sub_model.delete_subscription(sub.user_id, target.name)
            # elif within_lead:
            #     print(f'Already notified {sub.user_id} about this '
            #           f'{target.name} window.')
            # else:
            #     ttn = time_until - datetime.timedelta(seconds=sub.lead_time)
            #     print(f'Not yet time to notify about {target.name} for '
            #           f'{sub.user_id} ({ttn} to notification)')

    await asyncio.gather(*messages)
    if messages:
        print(f"Sent {len(messages)} subscription notifications.")


BUTTON_LISTENERS = {
    'unsubscribe': unsubscribe_listener,
    'refresh': refresh_listener
}
