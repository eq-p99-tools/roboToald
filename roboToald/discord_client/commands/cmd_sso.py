import disnake
from disnake.ext import commands

from roboToald import config
from roboToald.db.models import sso as sso_model

SSO_GUILDS = config.guilds_for_command('sso')

# TEMPORARY: This is a temporary solution to get the current function name
import inspect


def get_current_function_name():
    return inspect.currentframe().f_back.f_code.co_name


class SSOCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(description="SSO related commands",
                            guild_ids=SSO_GUILDS)
    async def sso(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @sso.sub_command(description="Show SSO setup/usage tutorial.")
    async def help(self, inter: disnake.ApplicationCommandInteraction):
        await inter.send(content="This is the SSO help command.")

    @sso.sub_command_group(description="Account related commands")
    async def account(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @account.sub_command(description="Create a new account", name="create")
    async def account_create(self, inter: disnake.ApplicationCommandInteraction, username: str, password: str):
        # Implement account creation logic
        account = sso_model.create_account(inter.guild_id, username, password)
        await inter.send(content=f"Created account: {account.real_user}")

    @account.sub_command(description="Show account details", name="show")
    async def account_show(self, inter: disnake.ApplicationCommandInteraction, username: str):
        # Implement account show logic
        account = sso_model.get_account(inter.guild_id, username)
        await inter.send(content=f"Account: {account.real_user}")

    @account.sub_command(description="List accounts", name="list")
    async def account_list(self, inter: disnake.ApplicationCommandInteraction, group: str = None, tag: str = None):
        # Implement account list logic
        account_list = sso_model.list_accounts(inter.guild_id, group, tag)
        await inter.send(content=f"Accounts: {[account.real_user for account in account_list]}")

    @account.sub_command(description="Update account password", name="update")
    async def account_update(self, inter: disnake.ApplicationCommandInteraction, username: str, new_password: str):
        # Implement account update logic
        account = sso_model.update_account(inter.guild_id, username, new_password)
        await inter.send(content=f"Updated account password: {account.real_user}")

    @account.sub_command(description="Delete an account", name="delete")
    async def account_delete(self, inter: disnake.ApplicationCommandInteraction, username: str):
        # Implement account delete logic
        sso_model.delete_account(inter.guild_id, username)
        await inter.send(content=f"Deleted account: {username}")

    @sso.sub_command_group(description="Tag related commands")
    async def tag(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @tag.sub_command(description="List tags", name="list")
    async def tag_list(self, inter: disnake.ApplicationCommandInteraction):
        # Implement tag list logic
        tags = sso_model.list_tags(inter.guild_id)
        await inter.send(content=f"Tags: {tags}")

    @tag.sub_command(description="Add a tag to an account", name="add")
    async def tag_add(self, inter: disnake.ApplicationCommandInteraction, username: str, tag: str):
        # Implement tag add logic
        tag = sso_model.tag_account(inter.guild_id, username, tag)
        await inter.send(content=f"Tagged account: {tag.account.real_user} with tag: {tag.tag}")

    @tag.sub_command(description="Remove a tag from an account", name="remove")
    async def tag_remove(self, inter: disnake.ApplicationCommandInteraction, username: str, tag: str):
        # Implement tag remove logic
        sso_model.untag_account(inter.guild_id, username, tag)
        await inter.send(content=f"Untagged account: {username} with tag: {tag}")

    @sso.sub_command_group(description="Group related commands")
    async def group(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @group.sub_command(description="Create a new group", name="create")
    async def group_create(self, inter: disnake.ApplicationCommandInteraction,
                           name: str,
                           role: disnake.Role = commands.Param(
                                 description="Role required for access to this group.")
                           ):
        # Implement group create logic
        account_group = sso_model.create_account_group(inter.guild_id, name, role.id)
        await inter.send(content=f"Created group: {account_group.group_name} accessible by role: <@&{role.id}>")

    @group.sub_command(description="Show group details", name="show")
    async def group_show(self, inter: disnake.ApplicationCommandInteraction, name: str):
        # Implement group show logic
        account_group = sso_model.get_account_group(inter.guild_id, name)
        await inter.send(content=f"Group: {account_group.group_name}\n"
                                 f"Accounts: {[account.real_user for account in account_group.accounts]}")

    @group.sub_command(description="List groups", name="list")
    async def group_list(self, inter: disnake.ApplicationCommandInteraction,
                         role: disnake.Role = commands.Param(
                                description="Role required for access to this group.",
                                default=None)
                         ):
        # Implement group list logic
        account_groups = sso_model.list_account_groups(inter.guild_id, role.id if role else None)
        await inter.send(content=f"Groups: {[group.group_name for group in account_groups]}")

    @group.sub_command(description="Delete a group", name="delete")
    async def group_delete(self, inter: disnake.ApplicationCommandInteraction, name: str):
        # Implement group delete logic
        sso_model.delete_account_group(inter.guild_id, name)
        await inter.send(content=f"Deleted group: {name}")

    @group.sub_command(description="Add a user to a group", name="add")
    async def group_add(self, inter: disnake.ApplicationCommandInteraction, group_name: str, username: str):
        # Implement group add logic
        sso_model.add_account_to_group(inter.guild_id, group_name, username)
        await inter.send(content=f"Added user: {username} to group: {group_name}")

    @group.sub_command(description="Remove a user from a group", name="remove")
    async def group_remove(self, inter: disnake.ApplicationCommandInteraction, group_name: str, username: str):
        # Implement group remove logic
        sso_model.remove_account_from_group(inter.guild_id, group_name, username)
        await inter.send(content=f"Removed user: {username} from group: {group_name}")

    @sso.sub_command_group(description="Alias related commands")
    async def alias(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @alias.sub_command(description="Create an alias for an account", name="create")
    async def alias_create(self, inter: disnake.ApplicationCommandInteraction, username: str, alias: str):
        # Implement alias create logic
        account_alias = sso_model.create_account_alias(inter.guild_id, username, alias)
        await inter.send(content=f"Created alias: {account_alias.alias} for account: {account_alias.account.real_user}")

    @alias.sub_command(description="List aliases", name="list")
    async def alias_list(self, inter: disnake.ApplicationCommandInteraction):
        # Implement alias list logic
        aliases = sso_model.list_account_aliases(inter.guild_id)
        await inter.send(content=f"Aliases: {[f'{alias.alias} => {alias.account.real_user}' for alias in aliases]}")

    @alias.sub_command(description="Delete an alias", name="delete")
    async def alias_delete(self, inter: disnake.ApplicationCommandInteraction, alias: str):
        # Implement alias delete logic
        sso_model.delete_account_alias(inter.guild_id, alias)
        await inter.send(content=f"Deleted alias: {alias}")

    @sso.sub_command_group(description="Audit related commands")
    async def audit(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @audit.sub_command(description="Audit an account", name="account")
    async def audit_account(self, inter: disnake.ApplicationCommandInteraction, account: str, max_records: int = 10):
        # Implement account audit logic
        await inter.send(content=f"Ran command: {get_current_function_name()}")

    @audit.sub_command(description="Audit a user", name="user")
    async def audit_user(self, inter: disnake.ApplicationCommandInteraction, user: int):
        # Implement user audit logic
        await inter.send(content=f"Ran command: {get_current_function_name()}")

    @audit.sub_command(description="Show audit statistics", name="statistics")
    async def audit_statistics(self, inter: disnake.ApplicationCommandInteraction):
        # Implement audit statistics logic
        await inter.send(content=f"Ran command: {get_current_function_name()}")

    @sso.sub_command_group(description="Access related commands")
    async def access(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @access.sub_command(description="Get your access key", name="get")
    async def access_get(self, inter: disnake.ApplicationCommandInteraction):
        # Implement access get logic
        access_key = sso_model.get_access_key(inter.guild_id, inter.user.id)
        await inter.send(content=f"Access key: {access_key.access_key}", ephemeral=True)

    @access.sub_command(description="Reset your access key", name="reset")
    async def access_reset(self, inter: disnake.ApplicationCommandInteraction):
        # Implement access reset logic
        access_key = sso_model.reset_access_key(inter.guild_id, inter.user.id)
        await inter.send(content=f"Access key reset: {access_key.access_key}", ephemeral=True)

    @access.sub_command(description="Revoke access from a user", name="revoke")
    async def access_revoke(self, inter: disnake.ApplicationCommandInteraction,
                            user: disnake.Member = commands.Param(
                                description="Member to audit."),
                            expiry_days: int = 0):
        # Implement access revoke logic
        # sso_model.revoke_user_access(inter.guild_id, inter.user.id)
        await inter.send(content=f"Revoked access to user: <@{user.id}>", ephemeral=True)


def setup(bot):
    bot.add_cog(SSOCommands(bot))
