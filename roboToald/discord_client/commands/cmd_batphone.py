import disnake
from disnake.ext import commands
import sqlalchemy.exc

from roboToald import constants
from roboToald.discord_client import base
from roboToald import db
from roboToald.db import models
from roboToald import utils


@base.DISCORD_CLIENT.slash_command(description="Batphone Registration")
async def batphone(inter):
    pass


@batphone.sub_command()
async def register(inter,
                   channel: disnake.TextChannel,
                   alert_url: str,
                   filter: str = commands.Param(default=None),
                   filter_regex: str = commands.Param(default=None),
                   filter_role: disnake.Role = commands.Param(default=None)):
    has_both_filters = filter and filter_regex
    has_one_filter = filter or filter_regex or filter_role
    if has_both_filters or not has_one_filter:
        await inter.response.send_message(
            "ERROR: You must supply one of `filter` or `filter_regex` "
            "(but not both), and/or `filter_role`.", ephemeral=True)
        return

    if not utils.validate_url(alert_url):
        await inter.response.send_message(
            "The URL you provided is not recognized as a supported alert "
            "service. Please provide a URL from one of the following "
            "services: \n"
            f"\u25b7 [SquadCast]({constants.SQUADCAST_WEBHOOK_URL})",
            # f"\u25b7 [PagerDuty]({constants.PAGERDUTY_WEBHOOK_URL})",
            ephemeral=True
        )
        return

    if filter:
        filter_regex = f".*{filter}.*"

    filter_role_id = None
    if filter_role:
        filter_role_id = filter_role.id

    with db.get_session() as session:
        alert = models.Alert(
            guild_id=inter.guild.id,
            channel_id=channel.id,
            user_id=inter.user.id,
            alert_regex=filter_regex,
            alert_url=alert_url,
            alert_role=filter_role_id
        )
        session.add(alert)
        try:
            session.commit()
        except sqlalchemy.exc.IntegrityError:
            print("User attempted to register a duplicate alert.")
            await inter.response.send_message(
                "Alert already exists.", ephemeral=True)
            return
        session.flush()
        print(f"Registered Alert ID: {alert.id}")
    await inter.response.send_message(
        f"Stored alert for <#{alert.channel_id}>: "
        f"`{alert.alert_regex}` \u2192 {alert.alert_url}",
        ephemeral=True)


@batphone.sub_command()
async def list(inter):
    alerts = models.get_alerts_for_user(inter.user.id, guild_id=inter.guild.id)

    if not alerts:
        await inter.response.send_message(
            "No alerts configured.", ephemeral=True)
        return

    await inter.response.send_message(
        embed=disnake.Embed(
            title="Your Batphone Alerts",
            description="To clear an alert, react to 🔕.\n"
                        "To test an alert, react to 🧪.",
            color=disnake.Color.blue()),
        ephemeral=True)
    for alert in alerts:
        desc = f"**Channel**: <#{alert.channel_id}>\n"
        if alert.alert_regex:
            desc += f"**Filter**: `{alert.alert_regex}`\n"
        if alert.alert_role:
            desc += f"**Role**: <@&{alert.alert_role}>\n"
        desc += f"**URL**: {alert.alert_url}"

        e = disnake.Embed(description=desc,
                          color=disnake.Color.blue())
        e.set_thumbnail(url=f"{constants.THUMBNAIL_META_TOKEN}{alert.id}")
        msg = await inter.followup.send(embed=e, wait=True, ephemeral=True)
        await msg.add_reaction(constants.TEST_EMOJI)
        await msg.add_reaction(constants.DELETE_EMOJI)


@base.DISCORD_CLIENT.event
async def on_reaction_add(reaction, user):
    message = reaction.message
    # Only react to our own messages
    if message.author.id != base.DISCORD_CLIENT.user.id:
        return
    # Don't respond to our own initial reactions
    if user.id == base.DISCORD_CLIENT.user.id:
        return
    # Only react if the message is an Alert embed
    try:
        thumb_url = message.embeds[0].thumbnail.url
        if not thumb_url.startswith(constants.THUMBNAIL_META_TOKEN):
            return
    except:
        return

    alert_id = int(thumb_url[len(constants.THUMBNAIL_META_TOKEN):])
    print(f"Reacted to Alert #{alert_id} with {reaction.emoji}")
    if reaction.emoji == constants.DELETE_EMOJI:
        print(f"Removing alert {alert_id}!")
        models.delete_alert(alert_id)
    elif reaction.emoji == constants.TEST_EMOJI:
        print(f"Testing alert {alert_id}!")
        alert = models.get_alert(alert_id)
        if alert:
            utils.send_alert(alert.alert_url, alert.id)
