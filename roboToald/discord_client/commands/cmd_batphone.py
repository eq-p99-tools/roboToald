import disnake
from disnake.ext import commands
import sqlalchemy.exc

from roboToald import config
from roboToald import constants
from roboToald.discord_client import base
from roboToald import db
from roboToald.db.models import alert as alert_model
from roboToald import utils

BATPHONE_GUILDS = config.guilds_for_command('batphone')
HELP_MESSAGE = (
    "To use this service, you must have an account created with [SquadCast](https://www.squadcast.com/).\n"
    "The service is free for our use, but you cannot sign up with a Gmail account, so you may need to use a different "
    "email address than you normally do.\n"
    "Once you have an account, you need to create a new `Service` (the name can be anything, like 'Batphone'), then "
    "add an `Alert Source` of type `Incident Webhook` and copy the `Webhook URL` to use here.\n"
    "**Note**: You can use the same `Webhook URL` for multiple alerts. This URL is unique to you, so don't share it "
    "with anyone else, or they may mercilessly troll you with fake alerts at odd hours.\n"
    "\n"
    "**Example Usage**:\n"
    "One of the most useful alerts I rely on is for quakes:"
    # Example Image will go after this in the embed
)


@base.DISCORD_CLIENT.slash_command(
    description="Batphone Registration",
    guild_ids=BATPHONE_GUILDS)
async def batphone(inter: disnake.ApplicationCommandInteraction):
    pass


@batphone.sub_command(description="Show batphone setup/usage tutorial.")
async def help(inter: disnake.ApplicationCommandInteraction):
    embed = disnake.Embed(
        title="Batphone Setup",
        description=HELP_MESSAGE
    )
    embed.set_image(url="https://i.imgur.com/LKnMHGT.png")
    await inter.send(embed=embed, ephemeral=True)


@batphone.sub_command(description="Register for a batphone.")
async def register(inter: disnake.ApplicationCommandInteraction,
                   channel: disnake.TextChannel = commands.Param(
                       description="The channel to watch for batphones."
                   ),
                   alert_url: str = commands.Param(
                       description="The Webhook URL to trigger when a batphone registration triggers."
                   ),
                   filter: str = commands.Param(
                       description="A plain-text filter to match. Only one of `filter` or `filter_regex` may be used. "
                                   "For example: `quake` should match any earthquake batphone.",
                       default=None
                   ),
                   filter_regex: str = commands.Param(
                       description="A regex filter to match. Only one of `filter` or `filter_regex` may be used. "
                                   "For example: `.*(TFA|MOTG|PROG).*` should match any ST Golem batphone.",
                       default=None
                   ),
                   filter_role: disnake.Role = commands.Param(
                       description="A role to match. This can be used with or without other filters. "
                                   "For example: selecting `@raiders` will match ANY message that pings the "
                                   "`@raiders` role.",
                       default=None
                   )):
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
        alert = alert_model.Alert(
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


@batphone.sub_command(description="List batphone registrations.")
async def list(inter: disnake.ApplicationCommandInteraction):
    alerts = alert_model.get_alerts_for_user(
        inter.user.id, guild_id=inter.guild.id)

    if not alerts:
        await inter.response.send_message(
            "No alerts configured.", ephemeral=True)
        return
    footer_text = "Active (triggered {0} times) <ID: {1}>"
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
        e.set_footer(text=footer_text.format(alert.trigger_count, alert.id))
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

        async def button_callback(button_inter,
                                  that_message=msg,
                                  that_alert=alert,
                                  that_embed=e,
                                  that_view=my_view):
            action = button_inter.component.emoji.name
            print(f"Interacted with Alert #{that_alert.id} with {action}")
            if action == constants.DELETE_EMOJI:
                print(f"Removing alert {that_alert.id}!")
                that_alert.delete()
                test_button.disabled = True
                delete_button.disabled = True
                clear_count_button.disabled = True
                that_embed.set_footer(text="Deleted")
                that_embed.colour = disnake.Color.darker_grey()
                await that_message.edit(view=that_view, embed=that_embed)
            elif action == constants.TEST_EMOJI:
                print(f"Testing alert {that_alert.id}!")
                utils.send_alert(
                    that_alert, f"Test of alert: {that_alert.alert_regex}")
                that_embed.set_footer(
                    text=footer_text.format(that_alert.trigger_count,
                                            that_alert.id))
                await that_message.edit(view=that_view, embed=that_embed)
            elif action == constants.CLEAR_EMOJI:
                print(f"Clearing counter for alert {that_alert.id}!")
                that_alert.reset_counter()
                that_embed.set_footer(
                    text=footer_text.format(that_alert.trigger_count,
                                            that_alert.id))
                await that_message.edit(view=that_view, embed=that_embed)

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
