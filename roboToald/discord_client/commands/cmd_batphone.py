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
async def help(inter):
    await inter.send("A help message would go here if there was one lolol",
                     ephemeral=True)


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

    first = True
    for alert in alerts:
        desc = f"**Channel**: <#{alert.channel_id}>\n"
        if alert.alert_regex:
            desc += f"**Filter**: `{alert.alert_regex}`\n"
        if alert.alert_role:
            desc += f"**Role**: <@&{alert.alert_role}>\n"
        desc += f"**URL**: {alert.alert_url}"

        e = disnake.Embed(description=desc,
                          color=disnake.Color.green())
        e.set_footer(text=f"Active (triggered {alert.trigger_count} times)")
        if first:
            await inter.response.send_message(embed=e, ephemeral=True)
            msg = await inter.original_message()
            first = False
        else:
            msg = await inter.followup.send(embed=e, wait=True, ephemeral=True)
        my_view = disnake.ui.View()
        test_button = disnake.ui.Button(
            label="Test", emoji=constants.TEST_EMOJI,
            style=disnake.ButtonStyle.green)
        delete_button = disnake.ui.Button(
            label="Delete", emoji=constants.DELETE_EMOJI,
            style=disnake.ButtonStyle.danger)
        clear_count_button = disnake.ui.Button(
            label="Clear Counter", emoji=constants.CLEAR_EMOJI,
            style=disnake.ButtonStyle.grey)

        async def button_callback(button_inter):
            action = button_inter.component.emoji.name
            print(f"Interacted with Alert #{alert.id} with {action}")
            if action == constants.DELETE_EMOJI:
                print(f"Removing alert {alert.id}!")
                alert.delete()
                test_button.disabled = True
                delete_button.disabled = True
                clear_count_button.disabled = True
                e.set_footer(text="Deleted")
                e.colour = disnake.Color.darker_grey()
                await msg.edit(view=my_view, embed=e)
            elif action == constants.TEST_EMOJI:
                print(f"Testing alert {alert.id}!")
                utils.send_alert(alert,
                                 f"Test of alert: {alert.alert_regex}")
                e.set_footer(text=f"Active (triggered {alert.trigger_count} times)")
                await msg.edit(view=my_view, embed=e)
            elif action == constants.CLEAR_EMOJI:
                alert.reset_counter()
                e.set_footer(text=f"Active (triggered {alert.trigger_count} times)")
                await msg.edit(view=my_view, embed=e)

            try:
                await button_inter.send()
            except disnake.errors.HTTPException:
                pass  # We know this isn't valid but that's fine
            return True

        test_button.callback = button_callback
        delete_button.callback = button_callback
        clear_count_button.callback = button_callback
        my_view.add_item(test_button)
        my_view.add_item(delete_button)
        my_view.add_item(clear_count_button)
        await msg.edit(view=my_view)
