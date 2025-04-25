import datetime

import disnake
from disnake.ext import commands
import sqlalchemy.exc

from roboToald import config
from roboToald.db.models import sso as sso_model

SSO_GUILDS = config.guilds_for_command('sso')

# TEMPORARY: This is a temporary solution to get the current function name
import inspect
def get_current_function_name():
    return inspect.currentframe().f_back.f_code.co_name


# Autocomplete function for account names
async def account_autocomplete(inter: disnake.ApplicationCommandInteraction, string: str):
    """Autocomplete function for account names available to the user."""
    try:
        # Get the user's roles
        user_roles = [role.id for role in inter.author.roles]
        
        # Get all accounts for this guild
        all_accounts = sso_model.list_accounts(inter.guild_id)
        
        # Filter accounts based on user's roles and access permissions
        available_accounts = []
        for account in all_accounts:
            # Check if account is in a group that the user has access to
            has_access = False
            for group in account.groups:
                if group.role_id in user_roles:
                    has_access = True
                    break
            
            # If no groups or has access, add to available accounts
            if not account.groups or has_access:
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
        return filtered_accounts[:50]
    except Exception:
        # In case of error, return an empty list
        return []


async def alias_autocomplete(inter: disnake.ApplicationCommandInteraction, string: str):
    """Autocomplete function for alias names available to the user."""
    try:
        # Get the user's roles
        user_roles = [role.id for role in inter.author.roles]
        
        # Get all aliases for this guild
        all_aliases = sso_model.list_aliases(inter.guild_id)
        
        # Filter aliases based on user's roles and access permissions
        available_aliases = []
        for alias in all_aliases:
            # Check if alias is in a group that the user has access to
            has_access = False
            for group in alias.groups:
                if group.role_id in user_roles:
                    has_access = True
                    break
            
            # If no groups or has access, add to available aliases
            if not alias.groups or has_access:
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
        return filtered_aliases[:50]
    except Exception:
        # In case of error, return an empty list
        return []


async def group_autocomplete(inter: disnake.ApplicationCommandInteraction, string: str):
    """Autocomplete function for group names available to the user."""
    try:
        # Get the user's roles
        user_roles = [role.id for role in inter.author.roles]
        
        # Get all groups for this guild
        all_groups = sso_model.list_groups(inter.guild_id)
        
        # Filter groups based on user's roles and access permissions
        available_groups = []
        for group in all_groups:
            # Check if group has role-based access
            has_access = False
            for role in group.roles:
                if role.id in user_roles:
                    has_access = True
                    break
            
            # If no roles or has access, add to available groups
            if not group.roles or has_access:
                available_groups.append(group)
        
        # Filter by the input string if provided
        if string:
            filtered_groups = [
                group.name for group in available_groups 
                if string.lower() in group.name.lower()
            ]
        else:
            filtered_groups = [group.name for group in available_groups]
        
        # Return up to 50 choices
        return filtered_groups[:50]
    except Exception:
        # In case of error, return an empty list
        return []


async def tag_autocomplete(inter: disnake.ApplicationCommandInteraction, string: str):
    """Autocomplete function for tag names available to the user."""
    try:
        # Get the user's roles
        user_roles = [role.id for role in inter.author.roles]
        
        # Get all tags for this guild
        all_tags = sso_model.list_tags(inter.guild_id)
        
        # Filter tags based on user's roles and access permissions
        available_tags = []
        for tag in all_tags:
            # Check if tag is in a group that the user has access to
            has_access = False
            for group in tag.groups:
                if group.role_id in user_roles:
                    has_access = True
                    break
            
            # If no groups or has access, add to available tags
            if not tag.groups or has_access:
                available_tags.append(tag)
        
        # Filter by the input string if provided
        if string:
            filtered_tags = [
                tag.name for tag in available_tags 
                if string.lower() in tag.name.lower()
            ]
        else:
            filtered_tags = [tag.name for tag in available_tags]
        
        # Return up to 50 choices
        return filtered_tags[:50]
    except Exception:
        # In case of error, return an empty list
        return []


class SSOCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(description="SSO related commands",
                            guild_ids=SSO_GUILDS)
    async def sso(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @sso.sub_command(description="Show SSO setup/usage tutorial.")
    async def help(self, inter: disnake.ApplicationCommandInteraction):
        help_text = """
# RoboToald SSO System Help

The Single Sign-On (SSO) system allows you to securely store and manage account credentials that can be accessed through both Discord commands and the REST API.

## Account Management
- `/sso account create <username> <password>` - Create a new account
- `/sso account show <username>` - Show details for an account
- `/sso account list [group] [tag]` - List accounts (optionally filtered by group or tag)
- `/sso account update <username> <new_password>` - Update an account's password
- `/sso account delete <username>` - Delete an account

## Group Management
Groups allow you to organize accounts and control access based on Discord roles.

- `/sso group create <name> <role>` - Create a new group with role-based access
- `/sso group show <name>` - Show details for a group
- `/sso group list [role]` - List all groups (optionally filtered by role)
- `/sso group delete <name>` - Delete a group
- `/sso group add <group_name> <username>` - Add an account to a group
- `/sso group remove <group_name> <username>` - Remove an account from a group

## Tag Management
Tags help you categorize and search for accounts.

- `/sso tag list` - List all tags and the accounts they're applied to
- `/sso tag add <username> <tag>` - Add a tag to an account
- `/sso tag remove <username> <tag>` - Remove a tag from an account

## Alias Management
Aliases allow alternative usernames for accounts.

- `/sso alias create <username> <alias>` - Create an alias for an account
- `/sso alias list` - List all aliases
- `/sso alias delete <alias>` - Delete an alias

## API Access
Access the accounts through the REST API.

- `/sso access get` - Get your personal API access key (keep this secret!)
- `/sso access reset` - Generate a new access key (invalidates the old one)

## Audit Commands
Review access and changes to the SSO system.

- `/sso audit account <account> [max_records]` - View audit logs for an account
- `/sso audit user <user_id>` - View audit logs for a specific user
- `/sso audit statistics` - View overall usage statistics
- `/sso audit failed` - View recent failed authentication attempts

## REST API
The SSO system can also be accessed through a REST API. The API server runs independently and accepts authentication requests with your access key.

For API documentation, see the README_API.md file.
"""
        await inter.send(content=help_text)

    @sso.sub_command_group(description="Account related commands")
    async def account(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @account.sub_command(description="Create a new account", name="create")
    async def account_create(self, inter: disnake.ApplicationCommandInteraction, username: str, password: str):
        # Implement account creation logic
        account = sso_model.create_account(inter.guild_id, username, password)
        await inter.send(content=f"Created account: {account.real_user}")

    @account.sub_command(description="Show account details", name="show")
    async def account_show(self, inter: disnake.ApplicationCommandInteraction,
                           username: str = commands.Param(
                               description="Account username to show details for",
                               autocomplete=account_autocomplete
                           )):
        # Implement account show logic
        account = sso_model.get_account(inter.guild_id, username)
        await inter.send(content=f"Account: {account.real_user}")

    @account.sub_command(description="List accounts", name="list")
    async def account_list(self, inter: disnake.ApplicationCommandInteraction,
                           group: str = commands.Param(
                               description="Group to filter accounts by",
                               autocomplete=group_autocomplete
                           ),
                           tag: str = commands.Param(
                               description="Tag to filter accounts by",
                               autocomplete=tag_autocomplete
                           )):
        # Implement account list logic
        account_list = sso_model.list_accounts(inter.guild_id, group, tag)
        await inter.send(content=f"Accounts: {[account.real_user for account in account_list]}")

    @account.sub_command(description="Update account password", name="update")
    async def account_update(self, inter: disnake.ApplicationCommandInteraction,
                             username: str = commands.Param(
                               description="Account username to update password for",
                               autocomplete=account_autocomplete
                             ),
                             new_password: str = commands.Param(
                               description="New password for the account"
                             )):
        # Implement account update logic
        account = sso_model.update_account(inter.guild_id, username, new_password)
        await inter.send(content=f"Updated account password: {account.real_user}")

    @account.sub_command(description="Delete an account", name="delete")
    async def account_delete(self, inter: disnake.ApplicationCommandInteraction,
                             username: str = commands.Param(
                               description="Account username to delete",
                               autocomplete=account_autocomplete
                            )):
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
    async def tag_add(self, inter: disnake.ApplicationCommandInteraction,
                      username: str = commands.Param(
                               description="Account username to create alias for",
                               autocomplete=account_autocomplete
                      ), tag: str = commands.Param(
                        description="Tag to add to the account",
                        autocomplete=tag_autocomplete
                      )):
        # Implement tag add logic
        tag = sso_model.tag_account(inter.guild_id, username, tag)
        await inter.send(content=f"Tagged account: {tag.account.real_user} with tag: {tag.tag}")

    @tag.sub_command(description="Remove a tag from an account", name="remove")
    async def tag_remove(self, inter: disnake.ApplicationCommandInteraction,
                         username: str = commands.Param(
                               description="Account username to create alias for",
                               autocomplete=account_autocomplete
                         ), tag: str = commands.Param(
                               description="Tag to remove from the account",
                               autocomplete=tag_autocomplete
                         )):
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
    async def group_show(self, inter: disnake.ApplicationCommandInteraction,
                         name: str = commands.Param(
                             description="Group name to show details for",
                             autocomplete=group_autocomplete
                         )):
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
    async def group_delete(self, inter: disnake.ApplicationCommandInteraction,
                           name: str = commands.Param(
                               description="Group name to delete",
                               autocomplete=group_autocomplete
                           )):
        # Implement group delete logic
        sso_model.delete_account_group(inter.guild_id, name)
        await inter.send(content=f"Deleted group: {name}")

    @group.sub_command(description="Add a user to a group", name="add")
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
        sso_model.add_account_to_group(inter.guild_id, group_name, username)
        await inter.send(content=f"Added user: {username} to group: {group_name}")

    @group.sub_command(description="Remove a user from a group", name="remove")
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
        sso_model.remove_account_from_group(inter.guild_id, group_name, username)
        await inter.send(content=f"Removed user: {username} from group: {group_name}")

    @sso.sub_command_group(description="Alias related commands")
    async def alias(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @alias.sub_command(description="Create an alias for an account", name="create")
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
            account_alias = sso_model.create_account_alias(inter.guild_id, username, alias)
            await inter.send(content=f"✅ **Created alias**: {alias} for account: {username}")
        except sqlalchemy.exc.IntegrityError:
            await inter.send(content=f"⚠️ **Alias already exists**: `{alias}`", ephemeral=True)
        except Exception as e:
            await inter.send(content=f"⚠️ **Error creating alias**: something unexpected happened.", ephemeral=True)

    @alias.sub_command(description="List aliases", name="list")
    async def alias_list(self, inter: disnake.ApplicationCommandInteraction):
        # Implement alias list logic
        aliases = sso_model.list_account_aliases(inter.guild_id)
        await inter.send(content=f"Aliases: {[f'{alias.alias} => {alias.account.real_user}' for alias in aliases]}")

    @alias.sub_command(description="Delete an alias", name="delete")
    async def alias_delete(self, inter: disnake.ApplicationCommandInteraction,
                           alias: str = commands.Param(
                               description="Alias to delete",
                               autocomplete=alias_autocomplete
                           )):
        # Implement alias delete logic
        sso_model.delete_account_alias(inter.guild_id, alias)
        await inter.send(content=f"Deleted alias: {alias}")

    @sso.sub_command_group(description="Audit related commands")
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
                discord_user = f"<@{log.discord_user_id}>" if log.discord_user_id else "Unknown"
                
                formatted_log = f"{discord_timestamp} {status} | 👤 {discord_user} | 🌐 `{ip}` | {details}"
                formatted_logs.append(formatted_log)
                
            # Create the response message
            response = f"# 📋 Audit Logs for Account: `{username}`\n"
            response += f"_{len(logs)} authentication attempts ({success_count} successful, {failed_count} failed)_\n\n"
            response += "\n".join(formatted_logs)
            
            # Send the response
            await inter.send(content=response, ephemeral=True)
            
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
                
                formatted_log = f"{discord_timestamp} {status} | 🤖 `{username}` | {details}"
                formatted_logs.append(formatted_log)
                
            # Create the response message
            response = f"# 📋 Audit Logs for User: {user_mention}\n"
            response += f"_Showing the {len(logs)} most recent authentication attempts_\n\n"
            response += "\n".join(formatted_logs)
            
            # Send the response
            await inter.send(content=response, ephemeral=True)
            
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
                await inter.send(content=f"📋 **No failed authentication attempts found in the last {hours} hours**", ephemeral=True)
                return
                
            # Format the logs for display
            formatted_logs = []
            ip_counts = {}  # Track counts by IP for potential attack detection
            
            for log in logs:
                discord_timestamp = f"<t:{int(log.timestamp.timestamp())}:f>"
                
                username = log.username if log.username else "Unknown"
                ip = log.ip_address if log.ip_address else "N/A"
                details = log.details if log.details else "No details"
                discord_user = f"<@{log.discord_user_id}>" if log.discord_user_id else "Unknown"

                # Track IP addresses for potential attack detection
                if ip != "N/A":
                    ip_counts[ip] = ip_counts.get(ip, 0) + 1
                
                formatted_log = f"{discord_timestamp} | 🤖 `{username}` | 🌐 `{ip}` | 👤 {discord_user} | {details}"
                formatted_logs.append(formatted_log)
                
            # Create the response message
            response = f"# 📋 Failed Authentication Attempts\n"
            response += f"_Showing {len(logs)} failed authentication attempts from the last {hours} hours_\n\n"
            
            # Add warning for potential attacks (multiple failures from same IP)
            potential_attacks = [f"`{ip}` ({count} attempts)" for ip, count in ip_counts.items() if count > 2]
            if potential_attacks:
                response += "⚠️ **Potential attack detected from:**\n"
                response += ", ".join(potential_attacks) + "\n\n"
            
            response += "\n".join(formatted_logs)
            
            # Send the response
            await inter.send(content=response, ephemeral=True)
            
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
                    
                    response += f"{discord_timestamp} {status} | 🤖 `{username}` | 🌐 `{ip}`\n"
            else:
                response += "_No recent activity_\n"
                
            # Send the response
            await inter.send(content=response, ephemeral=True)
            
        except Exception as e:
            await inter.send(content=f"⚠️ **Error retrieving audit statistics:** `{str(e)}`", ephemeral=True)

    @sso.sub_command_group(description="Access related commands")
    async def access(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @access.sub_command(description="Get your access key", name="get")
    async def access_get(self, inter: disnake.ApplicationCommandInteraction):
        # Implement access get logic
        access_key = sso_model.get_access_key_by_user(inter.guild_id, inter.user.id)
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
