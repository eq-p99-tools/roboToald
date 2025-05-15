import datetime

import disnake
from disnake.ext import commands
import sqlalchemy.exc
import io

from roboToald import config
from roboToald.db.models import sso as sso_model

SSO_GUILDS = config.guilds_for_command('sso')

# TEMPORARY: This is a temporary solution to get the current function name
import inspect
def get_current_function_name():
    return inspect.currentframe().f_back.f_code.co_name

USER_HELP_TEXT = """
# P99LoginProxy SSO System User Help

The Single Sign-On (SSO) system allows administrators to securely manage access to accounts via the P99LoginProxy.

## Login Access
- `/sso access get` - Get your personal API access key (keep this secret!)
- `/sso access reset` - Generate a new access key (invalidates the old one)

## Account Info
- `/sso account show <username>` - Show details for an account
- `/sso account list [group] [tag]` - List accounts (optionally filtered by group or tag)

## Tag Info
- `/sso tag list` - List all tags and the accounts they're applied to

## Alias Info
- `/sso alias list` - List all aliases
"""

ADMIN_HELP_TEXT = """
# P99LoginProxy SSO System Admin Help

The Single Sign-On (SSO) system allows you to securely manage access to accounts via the P99LoginProxy.

## Account Management
Accounts represent real bot accounts (eg: `guildcleric7`). They should be added to groups to control access.

- `/sso_admin account create <username> <password>` - Create a new account
- `/sso_admin account update <username> <new_password>` - Update an account's password
- `/sso_admin account delete <username>` - Delete an account

## Group Management
Groups allow you to organize accounts and control access based on Discord roles.

- `/sso_admin group create <name> <role>` - Create a new group with role-based access
- `/sso_admin group delete <name>` - Delete a group
- `/sso_admin group add <group_name> <username>` - Add an account to a group
- `/sso_admin group remove <group_name> <username>` - Remove an account from a group

## Tag Management
Tags help you categorize accounts and log in by "last accessed time".
Consider tags a named pool of accounts. For example, imagine you tag two accounts (`tovcleric1` and `tovcleric2`) as `tovcleric`.
A user can log in using `tovcleric` and will be assigned one of the two accounts, then the other, in round-robin fashion.

- `/sso_admin tag add <username> <tag>` - Add a tag to an account
- `/sso_admin tag remove <username> <tag>` - Remove a tag from an account

## Alias Management
Aliases allow alternative usernames for accounts.
For example, it might be a good idea to alias accounts with their character names, allowing login by character name.

- `/sso_admin alias create <username> <alias>` - Create an alias for an account
- `/sso_admin alias delete <alias>` - Delete an alias

## User Access Revocation
Revoking access to a user will prevent the user from logging in to otherwise authorized accounts via the P99LoginProxy Application.

- `/sso_admin revocation add <user_id> [expiry_days]` - Revoke access for a user for a specified number of days (0 = forever)
- `/sso_admin revocation list [user_id]` - List access revocations (optionally filtered by user)
- `/sso_admin revocation remove <user_id>` - Remove access revocations for a user

## Audit Commands
Review access and changes to the SSO system.

- `/sso_admin audit account <account> [max_records]` - View audit logs for an account
- `/sso_admin audit user <user_id>` - View audit logs for a specific user
- `/sso_admin audit statistics` - View overall usage statistics
- `/sso_admin audit failed` - View recent failed authentication attempts
"""

# Autocomplete function for account names
async def account_autocomplete(inter: disnake.ApplicationCommandInteraction, string: str):
    """Autocomplete function for account names available to the user."""
    try:
        # Get the user's roles
        user_roles = [role.id for role in inter.author.roles]
        user_is_admin = is_admin(user_roles, inter.guild_id)

        # Get all accounts for this guild
        all_accounts = sso_model.list_accounts(inter.guild_id)
        
        # Filter accounts based on user's roles and access permissions
        available_accounts = []
        for account in all_accounts:
            # Check if account is in a group that the user has access to
            has_access = False
            if user_is_admin:
                has_access = True
            else:
                for group in account.groups:
                    if group.role_id in user_roles:
                        has_access = True
                        break
            
            # If no groups or has access, add to available accounts
            if has_access:
                available_accounts.append(account)
        
        # Filter by the input string if provided
        if string:
            filtered_accounts = [
                account.real_user for account in available_accounts 
                if string.lower() in account.real_user.lower()
            ]
        else:
            filtered_accounts = [account.real_user for account in available_accounts]
        
        # Return up to 50 choices
        return filtered_accounts[:25]
    except Exception:
        # In case of error, return an empty list
        return []


async def alias_autocomplete(inter: disnake.ApplicationCommandInteraction, string: str):
    """Autocomplete function for alias names available to the user."""
    try:
        # Get the user's roles
        user_roles = [role.id for role in inter.author.roles]
        user_is_admin = is_admin(user_roles, inter.guild_id)
        
        # Get all aliases for this guild
        all_aliases = sso_model.list_account_aliases(inter.guild_id)
        
        # Filter aliases based on user's roles and access permissions
        available_aliases = []
        for alias in all_aliases:
            # Check if the account the alias is for is in a group that the user has access to
            has_access = False
            if user_is_admin:
                has_access = True
            else:
                for group in alias.account.groups:
                    if group.role_id in user_roles:
                        has_access = True
                        break
            
            # If has access, add to available aliases
            if has_access:
                available_aliases.append(alias)
        
        # Filter by the input string if provided
        if string:
            filtered_aliases = [
                alias.alias for alias in available_aliases 
                if string.lower() in alias.alias.lower()
            ]
        else:
            filtered_aliases = [alias.alias for alias in available_aliases]
        
        # Return up to 50 choices
        return filtered_aliases[:25]
    except Exception:
        # In case of error, return an empty list
        return []


async def account_and_alias_autocomplete(inter: disnake.ApplicationCommandInteraction, string: str):
    """Autocomplete function for account and alias names available to the user."""
    try:
        accounts = await account_autocomplete(inter, string)
        aliases = await alias_autocomplete(inter, string)
        return (accounts + aliases)[:25]
    except Exception:
        # In case of error, return an empty list
        return []


async def group_autocomplete(inter: disnake.ApplicationCommandInteraction, string: str):
    """Autocomplete function for group names available to the user."""
    try:
        # Get the user's roles
        user_roles = [role.id for role in inter.author.roles]
        user_is_admin = is_admin(user_roles, inter.guild_id)
        
        # Get all groups for this guild
        all_groups = sso_model.list_account_groups(inter.guild_id)
        
        # Filter groups based on user's roles and access permissions
        available_groups = []
        for group in all_groups:
            # Check if group has role-based access
            has_access = False
            if user_is_admin:
                has_access = True
            else:
                for role in user_roles:
                    if role in group.role_id:
                        has_access = True
                        break
    
            # If has access, add to available groups
            if has_access:
                available_groups.append(group)
        
        # Filter by the input string if provided
        if string:
            filtered_groups = [
                group.group_name for group in available_groups 
                if string.lower() in group.group_name.lower()
            ]
        else:
            filtered_groups = [group.group_name for group in available_groups]
        
        # Return up to 50 choices
        return filtered_groups[:25]
    except Exception as e:
        # In case of error, return an empty list
        return []


async def tag_autocomplete(inter: disnake.ApplicationCommandInteraction, string: str):
    """Autocomplete function for tag names available to the user."""
    try:
        # Get the user's roles
        user_roles = [role.id for role in inter.author.roles]
        user_is_admin = is_admin(user_roles, inter.guild_id)
        
        # Get all tags for this guild
        all_tags = sso_model.list_tags(inter.guild_id)
        
        # Filter tags based on user's roles and access permissions
        available_tags = []

        # There are a few possibilities for filtering.
        # 1. inter.options['tag'] is set:
        #    - We're in a tag function, in which case:
        #        - if inter.options['tag']['remove'] is set:
        #            - We're removing a tag, in which case:
        #                - if inter.options['tag']['remove']['username'] is set, we only want tags on that account
        #        - if inter.options['tag']['add'] is set:
        #            - We're adding a tag, in which case:
        #                - if inter.options['tag']['add']['username'] is set, we only want tags NOT already on that account
        # 2. inter.options['tag'] is not set:
        #    - We're not in a tag function, in which case:
        #        - We only want tags that are on accounts the user has access to
        tag_remove = False
        tag_add = False
        tag_username = None
        if 'tag' in inter.options:
            if 'remove' in inter.options['tag']:
                tag_remove = True
                tag_username = inter.options['tag']['remove']['username']
            if 'add' in inter.options['tag']:
                tag_add = True
                tag_username = inter.options['tag']['add']['username']
        for tag in all_tags:
            # Check if tag is on an account that the user has access to
            has_access = False
            if tag_remove:
                valid_tag = False
            else:
                valid_tag = True
            for account in all_tags[tag]:
                if tag_remove and tag_username == account:
                    valid_tag = True
                elif tag_add and tag_username == account:
                    valid_tag = False

                if user_is_admin:
                    has_access = True
                else:
                    for group in account.groups:
                        if group.role_id in user_roles:
                            has_access = True
                            break
            
            # If has access, add to available tags
            if has_access and valid_tag:
                available_tags.append(tag)
        
        # Filter by the input string if provided
        if string:
            filtered_tags = [
                tag for tag in available_tags 
                if string.lower() in tag.lower()
            ]
        else:
            filtered_tags = [tag for tag in available_tags]
        
        # Return up to 50 choices
        return filtered_tags[:25]
    except Exception as e:
        # In case of error, return an empty list
        return []


def is_admin(user_roles, guild_id):
    admin_roles = config.GUILD_SETTINGS.get(guild_id, {}).get('sso_admin_roles')
    for admin_role in admin_roles:
        if admin_role in user_roles:
            return True
    return False


def only_allow_admin():
    async def predicate(inter: disnake.ApplicationCommandInteraction):
        if not is_admin([role.id for role in inter.author.roles], inter.guild_id):
            return False
        return True
    return commands.check(predicate)


async def send_and_split(send_fn, message: str, ephemeral: bool = False, files: list = None):
    """Send a message, splitting it into chunks if it's too long.
    
    Args:
        send_fn: The function to use for sending (e.g., inter.send)
        message: The message content to send
        ephemeral: Whether the message should be ephemeral
        files: Optional list of disnake.File objects to attach to the last message chunk
    """
    max_length = 2000
    lines = message.splitlines(keepends=True)
    current_chunk = ''
    chunks = []
    
    # Collect all chunks
    for line in lines:
        if len(current_chunk) + len(line) > max_length:
            chunks.append(current_chunk)
            current_chunk = ''
        current_chunk += line
    if current_chunk:
        chunks.append(current_chunk)
    
    # Send all chunks except the last one
    for i in range(len(chunks) - 1):
        await send_fn(content=chunks[i], ephemeral=ephemeral,
                      allowed_mentions=disnake.AllowedMentions.none())
    
    # Send the last chunk with files if provided
    if chunks:
        if files:
            await send_fn(content=chunks[-1], ephemeral=ephemeral,
                          allowed_mentions=disnake.AllowedMentions.none(),
                          files=files)
        else:
            await send_fn(content=chunks[-1], ephemeral=ephemeral,
                          allowed_mentions=disnake.AllowedMentions.none())


class SSOCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_slash_command_error(self, inter: disnake.ApplicationCommandInteraction, error):
        if isinstance(error, commands.CheckFailure):
            await inter.send("You do not have permission to use this command.", ephemeral=True)
        else:
            raise error

    @commands.slash_command(description="SSO User commands",
                            guild_ids=SSO_GUILDS)
    async def sso(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @sso.sub_command(description="Show SSO usage tutorial.")
    async def help(self, inter: disnake.ApplicationCommandInteraction):
        help_text = USER_HELP_TEXT
        await send_and_split(inter.send, help_text, ephemeral=True)

    @sso.sub_command(description="Get your access key", name="get")
    async def access_get(self, inter: disnake.ApplicationCommandInteraction):
        # Implement access get logic
        access_key = sso_model.get_access_key_by_user(inter.guild_id, inter.user.id)
        await inter.send(content=f"🔑 **Access key:** `{access_key.access_key}`", ephemeral=True)

    @sso.sub_command(description="Reset your access key", name="reset")
    async def access_reset(self, inter: disnake.ApplicationCommandInteraction):
        # Implement access reset logic
        access_key = sso_model.reset_access_key(inter.guild_id, inter.user.id)
        await inter.send(content=f"🔑 **Access key reset:** `{access_key.access_key}`", ephemeral=True)

    @only_allow_admin()
    @commands.slash_command(description="SSO related commands",
                            guild_ids=SSO_GUILDS)
    async def sso_admin(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @sso_admin.sub_command(description="Show SSO Admin setup/usage tutorial.", name="help")
    async def admin_help(self, inter: disnake.ApplicationCommandInteraction):
        help_text = ADMIN_HELP_TEXT
        await send_and_split(inter.send, help_text, ephemeral=True)

    @sso.sub_command_group(description="Account related commands")
    async def account(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @account.sub_command(description="Show account details", name="show")
    async def account_show(self, inter: disnake.ApplicationCommandInteraction,
                           username: str = commands.Param(
                               description="Account username to show details for",
                               autocomplete=account_and_alias_autocomplete
                           )):
        # Implement account show logic
        try:
            account = sso_model.find_account_by_username(username, inter.guild_id)
            if not account:
                raise sso_model.SSOAccountNotFoundError
            group_names = '\n'.join([f'• `{group.group_name}`' for group in account.groups])
            group_string = f"\n🗂️ Groups:\n{group_names}" if group_names else ""
            tag_names = '\n'.join([f'• `{tag.tag}`' for tag in account.tags])
            tag_string = f"\n🏷️ Tags:\n{tag_names}" if tag_names else ""
            alias_names = '\n'.join([f'• `{alias.alias}`' for alias in account.aliases])
            alias_string = f"\n🔗 Aliases:\n{alias_names}" if alias_names else ""
            await inter.send(content=f"🤖 **Account:** `{account.real_user}`{group_string}{tag_string}{alias_string}", ephemeral=True)
        except sso_model.SSOAccountNotFoundError:
            await inter.send(content=f"⚠️🤖 **Account not found:** `{username}`", ephemeral=True)

    @account.sub_command(description="List accounts", name="list")
    async def account_list(self, inter: disnake.ApplicationCommandInteraction,
                           group: str = commands.Param(
                               description="Group to filter accounts by",
                               autocomplete=group_autocomplete,
                               default=None
                           ),
                           tag: str = commands.Param(
                               description="Tag to filter accounts by",
                               autocomplete=tag_autocomplete,
                               default=None
                           )):
        # Implement account list logic
        account_list = sso_model.list_accounts(inter.guild_id, group, tag)
        if not account_list:
            await inter.send(content="ℹ️ **No accounts found with the given filters.**", ephemeral=True)
            return
        formatted_accounts = ""
        for account in account_list:
            formatted_accounts += f"🤖 **{account.real_user}**:\n"
            if account.groups:
                group_names = ', '.join([f"{group.group_name}" for group in account.groups])
                group_string = f"🗂️ Groups: {group_names}"
                formatted_accounts += f"  →  {group_string}\n"
            if account.tags:
                tag_names = ', '.join([f"{tag.tag}" for tag in account.tags])
                tag_string = f"🏷️ Tags: {tag_names}"
                formatted_accounts += f"  →  {tag_string}\n"
            if account.aliases:
                alias_names = ', '.join([f"{alias.alias}" for alias in account.aliases])
                alias_string = f"🔗 Aliases: {alias_names}"
                formatted_accounts += f"  →  {alias_string}\n"
            if not account.groups and not account.tags and not account.aliases:
                formatted_accounts += "  →  No groups, tags, or aliases\n"
        await send_and_split(inter.send, f"**Accounts:**\n{formatted_accounts}", ephemeral=True)

    @sso_admin.sub_command_group(description="Account related commands", name="account")
    async def admin_account(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @admin_account.sub_command(description="Create a new account", name="create")
    async def account_create(self, inter: disnake.ApplicationCommandInteraction,
                             username: str = commands.Param(
                                 description="Username for the new account",
                             ),
                             password: str = commands.Param(
                                 description="Password for the new account"
                             ),
                             group: str = commands.Param(
                                 description="Group to add the account to",
                                 autocomplete=group_autocomplete,
                                 default=None
                             )):
        # Implement account creation logic
        try:
            account = sso_model.create_account(inter.guild_id, username, password, group)
            await inter.send(content=f"✨🤖{'🗂️' if group else ''} **Created account** `{account.real_user}`{' **in group** `' + group + '`' if group else ''}")
        except sqlalchemy.exc.IntegrityError:
            await inter.send(content=f"⚠️🤖 **Account already exists:** `{username}`", ephemeral=True)


    @admin_account.sub_command(description="Update account password", name="update")
    async def account_update(self, inter: disnake.ApplicationCommandInteraction,
                             username: str = commands.Param(
                               description="Account username to update password for",
                               autocomplete=account_autocomplete
                             ),
                             new_password: str = commands.Param(
                               description="New password for the account"
                             )):
        # Implement account update logic
        try:
            account = sso_model.update_account(inter.guild_id, username, new_password)
            await inter.send(content=f"🔑🤖 **Updated password** for account `{account.real_user}`")
        except sso_model.SSOAccountNotFoundError:
            await inter.send(content=f"⚠️🤖 **Account not found:** `{username}`", ephemeral=True)

    @admin_account.sub_command(description="Delete an account", name="delete")
    async def account_delete(self, inter: disnake.ApplicationCommandInteraction,
                             username: str = commands.Param(
                               description="Account username to delete",
                               autocomplete=account_autocomplete
                            )):
        # Implement account delete logic
        try:
            sso_model.delete_account(inter.guild_id, username)
            await inter.send(content=f"🗑️🤖 **Deleted account** `{username}`")
        except sqlalchemy.exc.NoResultFound:
            await inter.send(content=f"⚠️🤖 **Account not found:** `{username}`", ephemeral=True)

    @sso.sub_command_group(description="Tag related commands")
    async def tag(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @tag.sub_command(description="List tags", name="list")
    async def tag_list(self, inter: disnake.ApplicationCommandInteraction):
        # Implement tag list logic
        tags = sso_model.list_tags(inter.guild_id)
        if not tags:
            await inter.send(content="ℹ️ **No tags found in this server.**", ephemeral=True)
            return
        formatted = '\n'.join([f"🏷️ **{tag}**" for tag in tags])
        await send_and_split(inter.send, f"**Tags:**\n{formatted}", ephemeral=True)

    @tag.sub_command(description="Show a tag", name="show")
    async def tag_show(self, inter: disnake.ApplicationCommandInteraction,
                       tag: str = commands.Param(
                         description="Tag to show",
                         autocomplete=tag_autocomplete
                       )):
        # Implement tag show logic
        tags = sso_model.get_tag(inter.guild_id, tag)
        if not tags:
            await inter.send(content=f"⚠️ **Tag not found:** `{tag}`", ephemeral=True)
            return
            
        formatted = f"🏷️ **{tag}:**\n"
        files = []
        
        for tag_obj in tags:
            formatted += f"  →  🤖 `{tag_obj.account.real_user}`\n"
            # Check if this tag has a UI macro and we haven't already added it to files
            if tag_obj.ui_macro and not files:
                # Create a file object from the binary data
                macro_file = disnake.File(
                    fp=io.BytesIO(tag_obj.ui_macro.ui_macro_data),
                    filename=f"{tag}_macro.ini"
                )
                files.append(macro_file)

        if files:
            formatted += "  →  📄 UI Macro (attached)\n"
                
        # Send the response with any attached files
        await send_and_split(inter.send, formatted, files=files, ephemeral=True)

    @sso_admin.sub_command_group(description="Tag related commands", name="tag")
    async def admin_tag(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @admin_tag.sub_command(description="Add a tag to an account", name="add")
    async def tag_add(self, inter: disnake.ApplicationCommandInteraction,
                      username: str = commands.Param(
                               description="Account username to create alias for",
                               autocomplete=account_autocomplete
                      ), tag: str = commands.Param(
                        description="Tag to add to the account",
                        autocomplete=tag_autocomplete
                      )):
        # Implement tag add logic
        try:
            tag = sso_model.tag_account(inter.guild_id, username, tag)
            await inter.send(content=f"✨🏷️ **Tagged account** `{tag.account.real_user}` with tag `{tag.tag}`")
        except sqlalchemy.exc.IntegrityError:
            await inter.send(content=f"⚠️🏷️ **Tag already exists** for account `{username}`", ephemeral=True)

    @admin_tag.sub_command(description="Update a tag", name="update")
    async def tag_update(self, inter: disnake.ApplicationCommandInteraction,
                         tag: str = commands.Param(
                               description="Tag to update",
                               autocomplete=tag_autocomplete
                         ), new_name: str = commands.Param(
                               description="New tag name",
                               default=None
                         ), new_ui_macro_data: disnake.Attachment = commands.Param(
                               description="New UI macro data",
                               default=None
                         )):
        if new_ui_macro_data:
            if new_ui_macro_data.size > 1024 * 1024:
                await inter.send(content="⚠️ **Attachment too large** (max 1MB)", ephemeral=True)
                return
            new_ui_macro_data = await new_ui_macro_data.read()
        if new_name:
            new_name = new_name.lower()
            existing_tags = sso_model.list_tags(inter.guild_id)
            if new_name in existing_tags:
                await inter.send(content=f"⚠️ **Tag already exists:** `{new_name}`", ephemeral=True)
                return
        if new_name is None and new_ui_macro_data is None:
            await inter.send(content="⚠️ **No changes specified, no action taken.**", ephemeral=True)
            return

        try:
            sso_model.update_tag(inter.guild_id, tag, new_name, new_ui_macro_data)
            message = f"🏷️ **Updated tag** `{tag}`"
            if new_name:
                message += f" to `{new_name}`"
            if new_ui_macro_data:
                message += " with new UI macro data"
            message += "."
            await inter.send(content=message)
        except sso_model.SSOAccountTagNotFoundError:
            await inter.send(content=f"⚠️🏷️ **Tag not found** for account `{tag}`", ephemeral=True)

    @admin_tag.sub_command(description="Remove a tag from an account", name="remove")
    async def tag_remove(self, inter: disnake.ApplicationCommandInteraction,
                         username: str = commands.Param(
                               description="Account username to create alias for",
                               autocomplete=account_autocomplete
                         ), tag: str = commands.Param(
                               description="Tag to remove from the account",
                               autocomplete=tag_autocomplete
                         )):
        # Implement tag remove logic
        try:
            sso_model.untag_account(inter.guild_id, username, tag)
            await inter.send(content=f"🗑️🏷️ **Untagged account** `{username}` from tag `{tag}`")
        except sso_model.SSOAccountNotFoundError:
            await inter.send(content=f"⚠️🏷️🤖 **Account not found:** `{username}`", ephemeral=True)
        except sso_model.SSOAccountTagNotFoundError:
            await inter.send(content=f"⚠️🏷️ **Tag not found** for account `{username}`", ephemeral=True)

    @sso.sub_command_group(description="Group related commands")
    async def group(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @group.sub_command(description="Show group details", name="show")
    async def group_show(self, inter: disnake.ApplicationCommandInteraction,
                         name: str = commands.Param(
                             description="Group name to show details for",
                             autocomplete=group_autocomplete
                         )):
        # Implement group show logic
        try:
            account_group = sso_model.get_account_group(inter.guild_id, name)
            account_names = '\n'.join([f'• `{account.real_user}`' for account in account_group.accounts])
            await inter.send(content=f"🗂️ **Group:** `{account_group.group_name}`\n"
                                     f" → 🤖 Accounts:\n{account_names}", ephemeral=True)
        except sqlalchemy.exc.NoResultFound:
            await inter.send(content=f"⚠️🗂️ **Group not found:** `{name}`", ephemeral=True)

    @group.sub_command(description="List groups", name="list")
    async def group_list(self, inter: disnake.ApplicationCommandInteraction,
                         role: disnake.Role = commands.Param(
                             description="Role required for access to this group.",
                             default=None)
                         ):
        # Implement group list logic
        account_groups = sso_model.list_account_groups(inter.guild_id, role.id if role else None)
        if not account_groups:
            if role:
                await inter.send(content=f"ℹ️ **No groups found for role: <@&{role.id}>.**", ephemeral=True)
            else:
                await inter.send(content="ℹ️ **No groups found in this server.**", ephemeral=True)
            return
        formatted = '\n'.join([f"🗂️ `{group.group_name}` → <@&{group.role_id}>" for group in account_groups])
        await send_and_split(inter.send, f"**Groups:**\n{formatted}", ephemeral=True)

    @sso_admin.sub_command_group(description="Group related commands", name="group")
    async def admin_group(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @admin_group.sub_command(description="Create a new group", name="create")
    async def group_create(self, inter: disnake.ApplicationCommandInteraction,
                           name: str = commands.Param(
                               description="Name for the new group"),
                           role: disnake.Role = commands.Param(
                               description="Role required for access to this group.")
                           ):
        # Implement group create logic
        try:
            account_group = sso_model.create_account_group(inter.guild_id, name, role.id)
            await inter.send(content=f"✨🗂️ **Created group** `{account_group.group_name}` accessible by role <@&{role.id}>.",
                             allowed_mentions=disnake.AllowedMentions.none())
        except sqlalchemy.exc.IntegrityError:
            await inter.send(content=f"⚠️🗂️ **Group already exists:** `{name}`", ephemeral=True)

    @admin_group.sub_command(description="Add a user to a group", name="add")
    async def group_add(self, inter: disnake.ApplicationCommandInteraction,
                        group_name: str = commands.Param(
                            description="Group name to add user to",
                            autocomplete=group_autocomplete
                        ),
                        username: str = commands.Param(
                            description="Account username to add to the group",
                            autocomplete=account_autocomplete
                        )):
        # Implement group add logic
        try:
            sso_model.add_account_to_group(inter.guild_id, group_name, username)
            await inter.send(content=f"✨🤖🗂️ **Added user** `{username}` to group `{group_name}`")
        except sso_model.SSOAccountGroupNotFoundError:
            await inter.send(content=f"⚠️🗂️ **Group not found:** `{group_name}`", ephemeral=True)
        except sso_model.SSOAccountNotFoundError:
            await inter.send(content=f"⚠️🤖 **Account not found:** `{username}`", ephemeral=True)
        except sqlalchemy.exc.IntegrityError:
            await inter.send(content=f"⚠️🤖🗂️ **Account/group mapping already exists:** `{username}` : `{group_name}`", ephemeral=True)

    @admin_group.sub_command(description="Remove a user from a group", name="remove")
    async def group_remove(self, inter: disnake.ApplicationCommandInteraction,
                           group_name: str = commands.Param(
                               description="Group name to remove user from",
                               autocomplete=group_autocomplete
                           ),
                           username: str = commands.Param(
                               description="Account username to remove from the group",
                               autocomplete=account_autocomplete
                           )):
        # Implement group remove logic
        try:
            sso_model.remove_account_from_group(inter.guild_id, group_name, username)
            await inter.send(content=f"🗑️🤖🗂️ **Removed user** `{username}` from group `{group_name}`")
        except sso_model.SSOAccountGroupNotFoundError:
            await inter.send(content=f"⚠️🗂️ **Group not found:** `{group_name}`", ephemeral=True)
        except sso_model.SSOAccountNotFoundError:
            await inter.send(content=f"⚠️🤖 **Account not found:** `{username}`", ephemeral=True)
        except sqlalchemy.exc.IntegrityError:
            await inter.send(content=f"⚠️🤖🗂️ **Account/group mapping not found:** `{username}` : `{group_name}`", ephemeral=True)

    @admin_group.sub_command(description="Delete a group", name="delete")
    async def group_delete(self, inter: disnake.ApplicationCommandInteraction,
                           name: str = commands.Param(
                               description="Group name to delete",
                               autocomplete=group_autocomplete
                           )):
        # Implement group delete logic
        try:
            sso_model.delete_account_group(inter.guild_id, name)
            await inter.send(content=f"🗑️🗂️ **Deleted group** `{name}`")
        except sso_model.SSOAccountGroupNotFoundError:
            await inter.send(content=f"⚠️🗂️ **Group not found:** `{name}`", ephemeral=True)

    @sso.sub_command_group(description="Alias related commands")
    async def alias(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @alias.sub_command(description="List aliases", name="list")
    async def alias_list(self, inter: disnake.ApplicationCommandInteraction):
        # Implement alias list logic
        aliases = sso_model.list_account_aliases(inter.guild_id)
        if not aliases:
            await inter.send(content="ℹ️ **No aliases found on this server.**", ephemeral=True)
            return
        formatted = '\n'.join([f"🔗 `{alias.alias}` → `{alias.account.real_user}`" for alias in aliases])
        await send_and_split(inter.send, f"🔗 **Aliases:**\n{formatted}", ephemeral=True)

    @sso_admin.sub_command_group(description="Alias related commands", name="alias")
    async def admin_alias(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @admin_alias.sub_command(description="Create an alias for an account", name="create")
    async def alias_create(self, inter: disnake.ApplicationCommandInteraction,
                           username: str = commands.Param(
                               description="Account username to create alias for",
                               autocomplete=account_autocomplete
                           ),
                           alias: str = commands.Param(
                               description="Alias to create"
                           )):
        # Implement alias create logic
        try:
            sso_model.create_account_alias(inter.guild_id, username, alias)
            await inter.send(content=f"✨🔗 **Created alias** `{alias}` for account `{username}`")
        except sqlalchemy.exc.IntegrityError:
            await inter.send(content=f"⚠️🔗 **Alias already exists:** `{alias}`", ephemeral=True)
        except sso_model.SSOAccountNotFoundError:
            await inter.send(content=f"⚠️🤖 **Account not found:** `{username}`", ephemeral=True)

    @admin_alias.sub_command(description="Delete an alias", name="delete")
    async def alias_delete(self, inter: disnake.ApplicationCommandInteraction,
                           alias: str = commands.Param(
                               description="Alias to delete",
                               autocomplete=alias_autocomplete
                           )):
        # Implement alias delete logic
        try:
            account_name = sso_model.delete_account_alias(inter.guild_id, alias)
            await inter.send(content=f"🗑️🔗 **Deleted alias** `{alias}` from account `{account_name}`")
        except sso_model.SSOAccountAliasNotFoundError:
            await inter.send(content=f"⚠️🔗 **Alias not found:** `{alias}`", ephemeral=True)

    @sso_admin.sub_command_group(description="Audit related commands")
    async def audit(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @audit.sub_command(description="Audit an account", name="account")
    async def audit_account(self, inter: disnake.ApplicationCommandInteraction, 
                           username: str = commands.Param(
                               description="Account username to audit",
                               autocomplete=account_autocomplete
                           ),
                           max_records: int = commands.Param(
                               default=10,
                               description="Maximum number of records to display",
                               min_value=1,
                               max_value=50
                           )):
        """Show audit logs for a specific account."""
        try:
            account = sso_model.get_account(inter.guild_id, username)
            if not account:
                await inter.send(content=f"📋 **Account not found:** `{username}`", ephemeral=True)
                return

            # Get audit logs for this username
            logs = sso_model.get_audit_logs(
                limit=max_records,
                username=username,
                success=None
            )
            
            if not logs:
                await inter.send(content=f"📋 **No audit logs found for account:** `{username}`", ephemeral=True)
                return
                
            # Format the logs for display
            formatted_logs = []
            success_count = 0
            failed_count = 0
            
            for log in logs:
                discord_timestamp = f"<t:{int(log.timestamp.timestamp())}:f>"
                
                if log.success:
                    status = "✅"
                    success_count += 1
                else:
                    status = "❌"
                    failed_count += 1
                    
                ip = log.ip_address if log.ip_address else "N/A"
                details = log.details if log.details else "No details"
                discord_user = f"<@{log.discord_user_id}>" if log.discord_user_id else "`Unknown`"
                
                formatted_log = f"{status}\u2003🌐`{ip:<15}`\u2003👤{discord_user}\u2003📅{discord_timestamp}\u2003*{details}*"
                formatted_logs.append(formatted_log)
                
            # Create the response message
            response = f"# 📋 Audit Logs for Account: `{username}`\n"
            response += f"_{len(logs)} authentication attempts ({success_count} successful, {failed_count} failed)._\n\n"
            response += "\n".join(formatted_logs)
            
            # Send the response
            await inter.send(content=response, ephemeral=True)
        except sso_model.SSOAccountNotFoundError:
            await inter.send(content=f"⚠️🤖 **Account not found:** `{username}`", ephemeral=True)
        except Exception as e:
            await inter.send(content=f"⚠️ **Error retrieving audit logs:** `{str(e)}`", ephemeral=True)

    @audit.sub_command(description="Audit a user", name="user")
    async def audit_user(self, inter: disnake.ApplicationCommandInteraction, 
                         user: disnake.User = commands.Param(
                            None,
                            description="Discord user to audit (defaults to yourself)",
                         )):
        """Show audit logs for a specific Discord user."""
        try:
            # If no user is provided, use the current user
            if user is None:
                user = inter.author
                
            user_id = user.id
            user_mention = user.mention

            logs = sso_model.get_audit_logs_for_user_id(user_id)

            if not logs:
                await inter.send(content=f"📋 **No audit logs found for user:** {user_mention}", ephemeral=True)
                return
                
            # Format the logs for display
            formatted_logs = []
            for log in logs:
                discord_timestamp = f"<t:{int(log.timestamp.timestamp())}:f>"
                
                status = "✅" if log.success else "❌"
                username = log.username if log.username else "Unknown"
                details = log.details if log.details else "No details"
                ip = log.ip_address if log.ip_address else "N/A"
                
                formatted_log = f"{status}\u2003🌐`{ip:<15}`\u2003🤖`{username:<12}`\u2003📅{discord_timestamp}\u2003*{details}*"
                formatted_logs.append(formatted_log)
                
            # Create the response message
            response = f"# 📋 Audit Logs for User: {user_mention}\n"
            response += f"_Showing the {len(logs)} most recent authentication attempts_\n\n"
            response += "\n".join(formatted_logs)
            
            # Send the response
            await send_and_split(inter.send, response, ephemeral=True)
            
        except Exception as e:
            await inter.send(content=f"⚠️ **Error retrieving audit logs:** `{str(e)}`", ephemeral=True)

    @audit.sub_command(description="View failed authentication attempts", name="failed")
    async def audit_failed(self, inter: disnake.ApplicationCommandInteraction,
                           max_records: int = commands.Param(
                              default=10,
                              description="Maximum number of records to display",
                              min_value=1,
                              max_value=50
                           ),
                           hours: int = commands.Param(
                              default=24*7,
                              description=f"Show attempts from the last N hours (default: {24*7} hours = 1 week)",
                              min_value=1,
                              max_value=24 * 365  # 1 year
                           )):
        """Show recent failed authentication attempts across all accounts."""
        try:
            # Calculate the time threshold for filtering
            since = None
            if hours > 0:
                since = datetime.datetime.now() - datetime.timedelta(hours=hours)
            
            # Get failed audit logs for all accounts in this guild
            logs = sso_model.get_audit_logs(
                limit=max_records,
                success=False,
                since=since
            )

            accounts = sso_model.list_accounts(inter.guild_id)
            account_names = [account.real_user for account in accounts]

            # Filter by either guild_id or account.guild_id
            logs = [log for log in logs if log.guild_id == inter.guild_id or log.username in account_names]
            
            if not logs:
                await inter.send(content=f"📋 **No unacknowledged failed authentication attempts found in the last {hours} hours.**", ephemeral=True)
                return
                
            # Format the logs for display
            formatted_logs = []
            ip_counts = {}  # Track counts by IP for potential attack detection
            
            for log in logs:
                discord_timestamp = f"<t:{int(log.timestamp.timestamp())}:f>"
                
                username = log.username if log.username else "Unknown"
                ip = log.ip_address if log.ip_address else "N/A"
                details = log.details if log.details else "No details"
                discord_user = f"<@{log.discord_user_id}>" if log.discord_user_id else "`Unknown`"

                # Track IP addresses for potential attack detection
                if ip != "N/A":
                    ip_counts[ip] = ip_counts.get(ip, 0) + 1
                
                formatted_log = f"🌐`{ip:<15}`\u2003🤖`{username:<12}`\u2003📅{discord_timestamp}\u2003👤{discord_user}\u2003*{details}*"
                formatted_logs.append(formatted_log)
                
            # Create the response message
            response = f"# 📋 Failed Authentication Attempts\n"
            response += f"_Showing {len(logs)} failed authentication attempts from the last {hours} hours._\n\n"
            
            # Add warning for potential attacks (multiple failures from same IP)
            potential_attacks = [f"`{ip}` ({count} attempts)" for ip, count in ip_counts.items() if count > 2]
            if potential_attacks:
                response += "⚠️ **Potential attacks detected from:**\n"
                response += ", ".join(potential_attacks) + "\n\n"
            
            response += "\n".join(formatted_logs)
            
            # Send the response
            await send_and_split(inter.send, response, ephemeral=True)
            
        except Exception as e:
            await inter.send(content=f"⚠️ **Error retrieving audit logs:** `{str(e)}`", ephemeral=True)

    @audit.sub_command(description="Show audit statistics", name="statistics")
    async def audit_statistics(self, inter: disnake.ApplicationCommandInteraction):
        """Show overall statistics from the audit logs."""
        try:
            # Get all audit logs for this guild
            all_logs = sso_model.get_audit_logs(
                limit=5000,  # Get a large sample for statistics
                guild_id=inter.guild_id
            )
            
            if not all_logs:
                await inter.send(content="📊 **No audit logs found for this guild**", ephemeral=True)
                return
                
            # Calculate statistics
            total_attempts = len(all_logs)
            successful_attempts = sum(1 for log in all_logs if log.success)
            failed_attempts = total_attempts - successful_attempts
            
            # Get unique usernames and IP addresses
            unique_usernames = set(log.username for log in all_logs if log.username)
            unique_ips = set(log.ip_address for log in all_logs if log.ip_address)
            
            # Get the most recent logs
            recent_logs = all_logs[:10]  # Assuming logs are already sorted by timestamp desc
            
            # Calculate success rate
            success_rate = (successful_attempts / total_attempts) * 100 if total_attempts > 0 else 0
            
            # Format the statistics
            response = "# 📊 SSO Audit Statistics\n\n"
            response += "## Summary\n"
            response += f"🔢 **Total Authentication Attempts:** `{total_attempts}`\n"
            response += f"✅ **Successful Attempts:** `{successful_attempts}` (`{success_rate:.1f}%`)\n"
            response += f"❌ **Failed Attempts:** `{failed_attempts}`\n"
            response += f"🤖 **Unique Usernames Used:** `{len(unique_usernames)}`\n"
            response += f"🌐 **Unique IP Addresses:** `{len(unique_ips)}`\n\n"
            
            # Add recent activity
            response += "## Recent Activity\n"
            if recent_logs:
                for log in recent_logs:
                    discord_timestamp = f"<t:{int(log.timestamp.timestamp())}:f>"
                    
                    status = "✅" if log.success else "❌"
                    username = log.username if log.username else "Unknown"
                    ip = log.ip_address if log.ip_address else "N/A"
                    discord_user = f"<@{log.discord_user_id}>" if log.discord_user_id else "Unknown"
                    
                    response += f"{status}\u2003🌐`{ip:<15}`\u2003🤖`{username:<12}`\u2003👤{discord_user}\u2003📅{discord_timestamp}\u2003*{log.details}*\n"
            else:
                response += "_No recent activity_\n"
                
            # Send the response
            await send_and_split(inter.send, response, ephemeral=True)
            
        except Exception as e:
            await inter.send(content=f"⚠️ **Error retrieving audit statistics:** `{str(e)}`", ephemeral=True)

    @sso_admin.sub_command_group(description="Manage SSO access", name="revocation")
    async def admin_revocation(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @admin_revocation.sub_command(description="Revoke access from a user", name="add")
    async def revocation_add(self, inter: disnake.ApplicationCommandInteraction,
                            user: disnake.Member = commands.Param(
                                description="Member to audit."),
                            expiry_days: int = commands.Param(
                                default=0,
                                description="Number of days to revoke access for. 0 = permanent"),
                            details: str = commands.Param(
                                default=None,
                                description="Reason for revoking access.")
                            ):
        try:
            sso_model.revoke_user_access(inter.guild_id, inter.user.id, expiry_days, details)
            message = f"❌🔑 **Revoked access to user:** <@{user.id}>"
            message += f"\n* **Days:** {expiry_days if expiry_days > 0 else 'Permanent'}"
            if details:
                message += f"\n* **Reason:** {details}"
            await inter.send(content=message, allowed_mentions=disnake.AllowedMentions.none())
        except Exception as e:
            await inter.send(content=f"❌🔑 **Failed to revoke access to user:** <@{user.id}>\n{e}", ephemeral=True)

    @admin_revocation.sub_command(description="List access revocations", name="list")
    async def revocation_list(self, inter: disnake.ApplicationCommandInteraction,
                              user: disnake.Member = commands.Param(
                                description="Member to list access revocations for.",
                                default=None)):
        revocations = sso_model.get_user_access_revocations(guild_id=inter.guild_id, discord_user_id=user.id)
        if not revocations:
            await inter.send(content="ℹ️ **No access revocations found.**", ephemeral=True)
            return
        formatted = ""
        for revocation in revocations:
            expiry_str = f"{revocation.expiry_days} day{'s' if revocation.expiry_days > 1 else ''}" if revocation.expiry_days > 0 else 'Permanent'
            reason_str = f": `{revocation.details}`" if revocation.details else ""
            formatted += f"* <@{revocation.discord_user_id}> ({expiry_str}){reason_str}\n"
        await inter.send(content=f"🔑 **Access revocations:**\n{formatted}", ephemeral=True)
    
    @admin_revocation.sub_command(description="Remove access revocation", name="remove")
    async def revocation_remove(self, inter: disnake.ApplicationCommandInteraction,
                                user: disnake.Member = commands.Param(
                                description="Member to remove access revocation.")):
        try:
            sso_model.remove_access_revocation(inter.guild_id, user.id)
            await inter.send(content=f"🔑 **Access revocations disabled for user:** <@{user.id}>", allowed_mentions=disnake.AllowedMentions.none())
        except Exception as e:
            await inter.send(content=f"❌🔑 **Failed to disable access revocations for user:** <@{user.id}>\n{e}", ephemeral=True)

    @sso_admin.sub_command(description="Reset rate limit for an IP address", name="reset_rate_limit")
    async def reset_rate_limit(self, inter: disnake.ApplicationCommandInteraction,
                                     ip_address: str = commands.Param(
                                        description="IP address to reset rate limit for.")):
        try:
            updated = sso_model.clear_rate_limit(ip_address)
            if updated > 0:
                await inter.send(content=f"🔑 **Rate limit reset for IP:** `{ip_address}` *({updated} records found)*")
            else:
                await inter.send(content=f"🔑 **No rate limit entries found for IP:** `{ip_address}`", ephemeral=True)
        except Exception as e:
            await inter.send(content=f"❌🔑 **Failed to reset rate limit for IP:** `{ip_address}`\n{e}", ephemeral=True)


def setup(bot):
    bot.add_cog(SSOCommands(bot))
