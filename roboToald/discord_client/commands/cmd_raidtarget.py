import asyncio
import datetime
import time
from typing import Optional, Tuple

import disnake
from disnake.ext import commands

from roboToald import config
from roboToald.db.models import subscription as sub_model
from roboToald.discord_client import base
from roboToald.raidtargets import rt_data

RAIDTARGET_GUILDS = config.guilds_for_command("raidtarget")
MAX_AC_RESULTS = 25


@base.DISCORD_CLIENT.slash_command(description="Raid Target commands", guild_ids=RAIDTARGET_GUILDS)
async def raidtarget(inter: disnake.ApplicationCommandInteraction):
    pass


def autocomplete_raid_target(inter: disnake.ApplicationCommandInteraction, user_input: str):
    names = rt_data.RaidTargets.get_all_names(inter.guild_id)
    return [name for name in names if user_input.lower() in name.lower()][:MAX_AC_RESULTS]


def autocomplete_existing_subscription(inter: disnake.ApplicationCommandInteraction, user_input: str):
    subs = sub_model.get_subscriptions_for_user(inter.user.id, guild_id=inter.guild_id)
    return [sub.target for sub in subs]


@raidtarget.sub_command(description="Subscribe to a raid target timer", name="subscribe")
async def subscribe(
    inter: disnake.ApplicationCommandInteraction,
    target: str = commands.Param(autocomplete=autocomplete_raid_target, description="The name of the raid target"),
    lead_time_minutes: int = commands.Param(
        default=30, description="Number of minutes before the window to send the notification"
    ),
):
    lead_time = int(lead_time_minutes * 60)
    if not base.is_user_authorized(
        guild=inter.guild, user_id=inter.user.id, role_id=config.get_member_role(inter.guild_id)
    ):
        await inter.send(content="You are not authorized to subscribe to raid targets.", ephemeral=True)
        return

    valid_names = rt_data.RaidTargets.get_all_names(inter.guild_id)
    if target not in valid_names:
        await inter.send(content=f"`{target}` is not a valid raid target for this server.", ephemeral=True)
        return

    sub_db = sub_model.Subscription(
        user_id=inter.user.id,
        target=target,
        expiry=int(time.time() + datetime.timedelta(days=30).total_seconds()),
        guild_id=inter.guild_id,
        lead_time=lead_time,
    )
    try:
        sub_db.store()
        message = f"Subscribed to `{target}`."
    except Exception:
        message = (
            f"Failed to subscribe to `{target}`. Either this subscription "
            f"already exists, or something went *horribly wrong* "
            f"and everything is about to be on fire."
        )

    await inter.send(content=message, ephemeral=True)


@raidtarget.sub_command(description="Unsubscribe from a raid target timer", name="unsubscribe")
async def unsubscribe(
    inter: disnake.ApplicationCommandInteraction,
    target: str = commands.Param(
        autocomplete=autocomplete_existing_subscription, description="The name of the raid target"
    ),
):
    try:
        sub_model.delete_subscription(user_id=inter.user.id, target=target, guild_id=inter.guild_id)
        message = f"Unsubscribed from `{target}`."
    except Exception:
        message = (
            f"Failed to unsubscribe from `{target}`. Either this subscription "
            f"doesn't exist, or something went *horribly wrong* "
            f"and everything is about to be on fire."
        )

    await inter.send(content=message, ephemeral=True)


@raidtarget.sub_command(description="Unsubscribe from a raid target timer", name="subscriptions")
async def subscriptions(inter: disnake.ApplicationCommandInteraction):
    user_subs = sub_model.get_subscriptions_for_user(inter.user.id, guild_id=inter.guild_id)

    dm = None
    s = "s" if len(user_subs) > 1 else ""
    if user_subs:
        dm = await inter.user.send(content=f"Subscription{s}:")
    for sub in user_subs:
        embed = make_subscription_embed(sub)
        await inter.user.send(
            embed=embed,
            components=_subscription_dm_buttons(sub.target, sub.guild_id),
        )

    if user_subs:
        message = f"Sent {len(user_subs)} subscription{s} via DM: {dm.jump_url}"
    else:
        message = "No active subscriptions found."
    await inter.send(content=message, ephemeral=True)


def _make_button_id(action: str, target: str, guild_id: int) -> str:
    return f"{action}:{target}:{guild_id}"


def _subscription_dm_buttons(target: str, guild_id: int) -> list[disnake.ui.Button]:
    """Unsubscribe / Refresh row for subscription DMs."""
    return [
        disnake.ui.Button(
            label="Unsubscribe",
            style=disnake.ButtonStyle.danger,
            custom_id=_make_button_id("unsubscribe", target, guild_id),
        ),
        disnake.ui.Button(
            label="Refresh",
            style=disnake.ButtonStyle.success,
            custom_id=_make_button_id("refresh", target, guild_id),
        ),
    ]


def _parse_button_id(custom_id: str) -> Optional[Tuple[str, int]]:
    parts = custom_id.split(":", 2)
    if len(parts) == 3 and parts[0] in ("unsubscribe", "refresh"):
        try:
            return parts[1], int(parts[2])
        except ValueError:
            return None
    return None


def _resolve_target_guild_from_interaction(inter: disnake.MessageInteraction) -> Optional[Tuple[str, int]]:
    parsed = _parse_button_id(inter.component.custom_id)
    if parsed:
        return parsed
    # Legacy DMs: bare custom_id + target in embed title, guild_id in footer
    if inter.component.custom_id not in ("unsubscribe", "refresh"):
        return None
    if not inter.message.embeds:
        return None
    embed = inter.message.embeds[0]
    if not embed.title or not embed.footer or not embed.footer.text:
        return None
    try:
        return embed.title, int(embed.footer.text)
    except ValueError:
        return None


def make_subscription_embed(sub_obj: sub_model.Subscription) -> disnake.Embed:
    last_notified = f"<t:{sub_obj.last_notified}:R>" if sub_obj.last_notified else "Never"
    embed = disnake.Embed(title=sub_obj.target)
    embed.add_field("Lead Time", "{:0>8}".format(str(datetime.timedelta(seconds=sub_obj.lead_time))))
    embed.add_field("Last Notification", last_notified)
    embed.add_field("Expires", f"<t:{sub_obj.expiry}:R>")
    return embed


def _copy_embed_update_expiry(old: disnake.Embed, new_sub: sub_model.Subscription) -> disnake.Embed:
    """Duplicate the message embed and only change the Expires field (subscription refresh)."""
    data = old.to_dict()
    fields = list(data.get("fields") or [])
    expiry_str = f"<t:{new_sub.expiry}:R>"
    updated = False
    for field in fields:
        if field.get("name") == "Expires":
            field["value"] = expiry_str
            updated = True
            break
    if not updated:
        fields.append({"name": "Expires", "value": expiry_str, "inline": False})
    data["fields"] = fields
    return disnake.Embed.from_dict(data)


async def refresh_listener(inter: disnake.MessageInteraction):
    resolved = _resolve_target_guild_from_interaction(inter)
    if not resolved:
        await inter.response.defer()
        return
    target, guild_id = resolved
    user_id = inter.user.id
    new_sub = sub_model.refresh_subscription(user_id=user_id, target=target, guild_id=guild_id)
    if new_sub:
        old_embed = inter.message.embeds[0] if inter.message.embeds else None
        if old_embed:
            next_embed = _copy_embed_update_expiry(old_embed, new_sub)
        else:
            next_embed = make_subscription_embed(sub_obj=new_sub)
        await inter.message.edit(
            content="Refreshed.",
            embeds=[next_embed],
            components=_subscription_dm_buttons(new_sub.target, new_sub.guild_id),
        )
    await inter.response.defer()


async def unsubscribe_listener(inter: disnake.MessageInteraction):
    resolved = _resolve_target_guild_from_interaction(inter)
    if not resolved:
        await inter.response.defer()
        return
    target, guild_id = resolved
    user_id = inter.user.id
    deleted = sub_model.delete_subscription(user_id=user_id, target=target, guild_id=guild_id)
    if deleted:
        await inter.message.edit(
            content=f"Unsubscribed from target `{target}`.",
            embeds=[],
            components=[],
        )
    await inter.response.defer()


def make_announce_embed(
    active_window: rt_data.RaidWindow,
    sub: sub_model.Subscription,
) -> disnake.Embed:
    embed = disnake.Embed()
    raid_target = active_window.target
    embed.title = f":boom:** {raid_target.name} **:boom:"
    embed.add_field("Start", f"<t:{active_window.start}:R>")
    embed.add_field("End", f"<t:{active_window.end}:R>")
    next_window = active_window.get_next()
    if next_window:
        embed.add_field("Next (estimated)", f"<t:{next_window.start}:R>")
    embed.add_field("Expires", f"<t:{sub.expiry}:R>")
    lead_fmt = "{:0>8}".format(str(datetime.timedelta(seconds=sub.lead_time)))
    embed.add_field("Lead Time", lead_fmt)
    return embed


async def announce_subscriptions():
    sub_model.clean_expired_subscriptions()
    subs_for_notify = sub_model.get_subscriptions_for_notification()

    guild_sub_map: dict[int, dict[str, list]] = {}
    for sub in subs_for_notify:
        guild_subs = guild_sub_map.setdefault(sub.guild_id, {})
        guild_subs.setdefault(sub.target, []).append(sub)

    now = time.time()
    messages = []

    for guild_id, sub_map in guild_sub_map.items():
        soon_threshold = config.get_raidtargets_soon_threshold(guild_id)
        raid_targets = rt_data.RaidTargets.get_targets(guild_id)

        for target in raid_targets:
            if target.name not in sub_map:
                continue
            active_window = target.get_active_window(now, soon_threshold=soon_threshold)
            if not active_window:
                continue
            time_until = active_window.get_time_until(now)
            for sub in sub_map[target.name]:
                within_lead = time_until <= datetime.timedelta(seconds=sub.lead_time)
                already_notified = sub.last_window_start == active_window.start
                if within_lead and not already_notified:
                    if base.is_user_authorized(
                        guild=base.DISCORD_CLIENT.get_guild(sub.guild_id),
                        user_id=sub.user_id,
                        role_id=config.get_member_role(sub.guild_id),
                    ):
                        user = base.DISCORD_CLIENT.get_user(sub.user_id)
                        if user:
                            embed = make_announce_embed(active_window, sub)
                            components = _subscription_dm_buttons(target.name, sub.guild_id)
                            messages.append(user.send(embed=embed, components=components))
                            sub_model.mark_subscription_sent(
                                sub.user_id,
                                target.name,
                                guild_id=sub.guild_id,
                                start_time=active_window.start,
                            )
                        else:
                            print(f"Could not load user for DM: {sub.user_id}")
                    else:
                        print(
                            f"User `{sub.user_id}` did not have the required role, "
                            f"removing watch `{target.name}`."
                        )
                        sub_model.delete_subscription(sub.user_id, target.name, guild_id=sub.guild_id)

    await asyncio.gather(*messages)
    if messages:
        print(f"Sent {len(messages)} subscription notifications.")


BUTTON_LISTENERS = {"unsubscribe": unsubscribe_listener, "refresh": refresh_listener}
