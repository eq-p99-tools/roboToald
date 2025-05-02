#!/usr/bin/env python
"""
Script to import accounts from a CSV file into the SSO database.

Usage:
    python import_accounts.py <guild_id> <accounts_filename>

Format of the accounts file (CSV):
    account_name,account_password,group_name,aliases,tags

Where:
    - aliases and tags are pipe-delimited lists
    - Example: account1,password1,group1,alias1|alias2,tag1|tag2
"""
import argparse
import csv
import os
import sys

# Add parent directory to path so we can import roboToald modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from roboToald.db.models import sso as sso_model


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Import accounts from a CSV file into the SSO database.')
    parser.add_argument('guild_id', type=int, help='Guild ID to import accounts into')
    parser.add_argument('accounts_file', type=str, help='Path to the CSV file containing account data')
    return parser.parse_args()


def get_existing_groups(guild_id: int) -> list[str]:
    """Get a list of existing group names for the guild."""
    try:
        groups = sso_model.list_account_groups(guild_id)
        return [group.group_name for group in groups]
    except Exception as e:
        print(f"Error retrieving groups: {e}")
        return []


def process_account(
    guild_id: int, 
    account_name: str, 
    account_password: str, 
    group_name: str, 
    aliases_str: str, 
    tags_str: str,
    existing_groups: list[str]
) -> tuple[bool, str]:
    """
    Process a single account entry.
    
    Returns:
        Tuple of (success, error_message)
    """
    # Check if group exists
    if group_name and group_name not in existing_groups:
        return False, f"Group '{group_name}' does not exist in guild {guild_id}"
    
    try:
        # Check if account already exists
        try:
            sso_model.get_account(guild_id, account_name)
            print(f"Account '{account_name}' already exists, updating...")
            sso_model.update_account(guild_id, account_name, account_password)
        except sso_model.SSOAccountNotFoundError:
            # Create new account
            print(f"Creating account '{account_name}'...")
            sso_model.create_account(guild_id, account_name, account_password, group_name)
        
        # Process aliases if provided
        if aliases_str:
            aliases = [alias.strip() for alias in aliases_str.split('|') if alias.strip()]
            for alias in aliases:
                try:
                    print(f"Adding alias '{alias}' to account '{account_name}'...")
                    sso_model.create_account_alias(guild_id, account_name, alias)
                except Exception as e:
                    print(f"Warning: Could not add alias '{alias}' to account '{account_name}': {e}")
        
        # Process tags if provided
        if tags_str:
            tags = [tag.strip() for tag in tags_str.split('|') if tag.strip()]
            for tag in tags:
                try:
                    print(f"Adding tag '{tag}' to account '{account_name}'...")
                    sso_model.tag_account(guild_id, account_name, tag)
                except Exception as e:
                    print(f"Warning: Could not add tag '{tag}' to account '{account_name}': {e}")
        
        return True, ""
    except Exception as e:
        return False, f"Error processing account '{account_name}': {e}"


def import_accounts(guild_id: int, accounts_file: str) -> None:
    """Import accounts from a CSV file into the SSO database."""
    # Get existing groups
    existing_groups = get_existing_groups(guild_id)
    print(f"Found {len(existing_groups)} existing groups in guild {guild_id}")
    
    # List to store accounts that failed to import
    error_accounts = []
    
    # Process the CSV file
    with open(accounts_file, 'r') as csvfile:
        reader = csv.reader(csvfile)
        
        # Track statistics
        total_accounts = 0
        successful_accounts = 0
        
        for row in reader:
            # Ensure we have at least the required fields
            if len(row) < 3:
                error_message = "Row has fewer than 3 columns"
                print(f"Error: {error_message}")
                error_accounts.append(row + [error_message])
                continue

            # Skip header row
            if total_accounts == 0 and row[0].lower().startswith('account'):
                continue
            total_accounts += 1
            
            # Extract fields
            account_name = row[0].strip()
            account_password = row[1].strip()
            group_name = row[2].strip()
            
            # Optional fields
            aliases_str = row[3].strip() if len(row) > 3 else ""
            tags_str = row[4].strip() if len(row) > 4 else ""
            
            print(f"Processing account '{account_name}'...")
            success, error_message = process_account(
                guild_id, account_name, account_password, group_name, 
                aliases_str, tags_str, existing_groups
            )
            
            if success:
                successful_accounts += 1
            else:
                print(f"Error: {error_message}")
                error_accounts.append(row + [error_message])
    
    # Write error accounts to a file if there are any
    if error_accounts:
        error_file = "error_accounts.csv"
        with open(error_file, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['account_name', 'account_password', 'group_name', 'aliases', 'tags', 'error'])
            writer.writerows(error_accounts)
        print(f"Wrote {len(error_accounts)} failed accounts to {error_file}")
    
    # Print summary
    print(f"\nImport summary:")
    print(f"Total accounts processed: {total_accounts}")
    print(f"Successfully imported: {successful_accounts}")
    print(f"Failed to import: {len(error_accounts)}")


def main():
    """Main entry point for the script."""
    args = parse_arguments()
    
    if not os.path.exists(args.accounts_file):
        print(f"Error: File '{args.accounts_file}' does not exist.")
        return
    
    print(f"Importing accounts into guild {args.guild_id} from file '{args.accounts_file}'...")
    import_accounts(args.guild_id, args.accounts_file)


if __name__ == "__main__":
    main()
