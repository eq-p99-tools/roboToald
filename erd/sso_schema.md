# RoboToald SSO Database Schema

## Tables and Relationships

### 1. SSOAccount
- **Description**: Represents an EQ bot account
- **Columns**:
  - `id` (Integer, Primary Key, Auto-increment)
  - `guild_id` (Integer, Not Null)
  - `real_user` (String(255), Not Null)
  - `real_pass` (EncryptedType(String(255)), Not Null)
  - `last_login` (DateTime, Default: datetime.datetime.min)
- **Indexes**:
  - Unique Constraint: `uq_guild_id_real_user` on (`guild_id`, `real_user`)
- **Relationships**:
  - Many-to-Many with `SSOAccountGroup` through `account_group_mapping`
  - One-to-Many with `SSOTag` (has many tags)
  - One-to-Many with `SSOAccountAlias` (has many aliases)

### 2. SSOAccountGroup
- **Description**: Represents a group of accounts with specific role permissions
- **Columns**:
  - `id` (Integer, Primary Key, Auto-increment)
  - `guild_id` (Integer, Not Null)
  - `group_name` (String(255), Not Null)
  - `role_id` (Integer, Not Null)
- **Indexes**:
  - Unique Constraint: `uq_guild_id_group_name` on (`guild_id`, `group_name`)
- **Relationships**:
  - Many-to-Many with `SSOAccount` through `account_group_mapping`

### 3. account_group_mapping
- **Description**: Junction table for the many-to-many relationship between accounts and groups
- **Columns**:
  - `id` (Integer, Primary Key)
  - `account_id` (Integer, Foreign Key to `SSOAccount.id`)
  - `group_id` (Integer, Foreign Key to `SSOAccountGroup.id`)

### 4. SSOAccessKey
- **Description**: Stores access keys for Discord users to authenticate with the API
- **Columns**:
  - `id` (Integer, Primary Key, Auto-increment)
  - `guild_id` (Integer, Not Null)
  - `discord_user_id` (Integer, Not Null)
  - `access_key` (EncryptedType(String(255)), Unique, Indexed)
- **Indexes**:
  - Unique Constraint: `uq_guild_id_discord_user_id` on (`guild_id`, `discord_user_id`)
  - Index on `access_key`

### 5. SSOTag
- **Description**: Tags associated with accounts for easier grouping and searching
- **Columns**:
  - `id` (Integer, Primary Key, Auto-increment)
  - `guild_id` (Integer, Not Null)
  - `tag` (String(255), Not Null)
  - `account_id` (Integer, Foreign Key to `SSOAccount.id`)
- **Indexes**:
  - Unique Constraint: `uq_tag_account_id` on (`tag`, `account_id`)
- **Relationships**:
  - Many-to-One with `SSOAccount` (belongs to an account)

### 6. SSOAccountAlias
- **Description**: Alternative names for accounts
- **Columns**:
  - `id` (Integer, Primary Key, Auto-increment)
  - `guild_id` (Integer, Not Null)
  - `alias` (String(255), Not Null)
  - `account_id` (Integer, Foreign Key to `SSOAccount.id`)
- **Indexes**:
  - Unique Constraint: `uq_alias_guild_id` on (`alias`, `guild_id`)
- **Relationships**:
  - Many-to-One with `SSOAccount` (belongs to an account)

### 7. SSOAuditLog
- **Description**: Audit log for SSO authentication attempts through the API
- **Columns**:
  - `id` (Integer, Primary Key, Auto-increment)
  - `timestamp` (DateTime, Default: current timestamp)
  - `ip_address` (String(45), Nullable) - IPv6 can be up to 45 chars
  - `username` (String(255), Not Null)
  - `success` (Boolean, Default: False)
  - `discord_user_id` (Integer, Nullable)
  - `account_id` (Integer, Nullable)
  - `guild_id` (Integer, Nullable)
  - `details` (String(255), Nullable)

## Entity Relationship Diagram

Please refer to the [SSO ERD](./sso_erd.svg) for a visual representation of this table.

## Key Database Operations

1. **Authentication Flow**:
   - User provides username and password to the API
   - System looks up the password in `SSOAccessKey` to find the Discord user ID
   - System checks if the user has access to the requested account
   - If authorized, returns the real credentials from `SSOAccount`
   - Creates an entry in `SSOAuditLog` for the authentication attempt

2. **Account Management**:
   - Accounts can be created, updated, and deleted
   - Accounts can be assigned to groups for role-based access control
   - Accounts can have tags for categorization
   - Accounts can have aliases for alternative names

3. **Security Features**:
   - Passwords and access keys are stored encrypted
   - Failed authentication attempts are logged
   - IP-based rate limiting prevents brute force attacks
   - Audit logs track all authentication activity

## Notes on NULL Values

For failed authentication attempts, the `guild_id` field in `SSOAuditLog` might be NULL. When filtering audit logs by guild_id, a special OR condition is used to include both attempts with a matching guild_id and those with NULL guild_id.

## Recent Updates

1. **API Server Enhancements**:
   - Added support for running with or without TLS based on certificate availability
   - Improved handling of X-Forwarded-For headers for proper client IP identification
   - Added configurable forwarded_allow_ips setting to control trusted proxy IPs

2. **Account Management**:
   - Modified last_login field to use datetime.min as default value instead of NULL
   - Changed account sorting in tag-based lookups to prioritize least recently used accounts
   - Added rate limiting configuration with shorter timeframe (10 minutes) and lower threshold (20 attempts)

3. **Utility Scripts**:
   - Added import_accounts.py script for bulk importing accounts from CSV files
   - CSV format supports account credentials, group assignment, aliases, and tags
