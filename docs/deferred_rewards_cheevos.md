# Deferred: Rewards / Cheevos System (Reward Server)

This feature was part of the batphone-bot Ruby application but has been deferred from the initial migration into roboToald. This document captures the full plan for later implementation.

## Overview

The Ruby bot operated on a **second Discord server** (`REWARD_SERVER_ID`) dedicated to managing "cheevos" (achievement-based DKP rewards). Users could earn rewards that were submitted to EQdkp Plus as adjustments.

## Database Tables (already exist in PG)

### `cheevos`
- `id` (PK), `name`, `category`, `description`, `dkp` (integer), `max_allowed` (integer)
- Loaded from Google Sheets via `$reload`

### `rewards`
- `id` (PK), `reward_id` (FK -> cheevos.id), `character_id` (FK -> characters.id), `eqdkp_user_id`, `eqdkp_adjustment_id`
- `eqdkp_adjustment_id` is null until submitted

## Ruby Commands to Port

All commands were restricted to `REWARD_SERVER_ID`.

### `$list`
- Lists all cheevos grouped by category
- No permission required

### `$reward <cheevo_id> <character>`
- Requires `:reward` permission
- Creates a `Reward` row linking a cheevo to a character
- Enforces `cheevos.max_allowed` per user (counts existing rewards for that cheevo+user)
- If invoked in a thread, reacts with checkmark on parent message

### `$submit` / `$submit all`
- Requires `:submit` permission (on reward server)
- Queues `RewardSubmitJob` (Sidekiq) which:
  - Iterates pending rewards (where `eqdkp_adjustment_id` is null)
  - For each, calls `EqdkpPublisher#create_reward_adjustment` with:
    - Character, cheevo DKP value, reason string
    - Uses `REWARD_ADJUSTMENT_EVENT_ID` (separate from raid adjustment event)
  - Stores returned `adjustment_id` on the reward row

### `$status`
- Requires no special permission
- Shows pending (unsubmitted) rewards as embeds

### `$report <id_or_character>`
- Requires `:reward_report` permission
- If numeric: shows details for that reward ID
- If string: shows all rewards for that character

### `-<reward_record_id>`
- Requires `:remove_reward` permission
- Deletes the reward row

## Implementation Plan

### New Files
- `roboToald/db/raid_models/reward.py` -- `Cheevo` and `Reward` SQLAlchemy models (inherit from `RaidBase`)
- `roboToald/discord_client/commands/cmd_reward.py` -- disnake Cog with slash commands

### Slash Commands
Register on `reward_server_id` (from `batphone.ini` `[raid]` section).

- `/reward list` -- cheevos by category
- `/reward give <cheevo_id> <character>` -- with autocomplete on cheevo name and character name
- `/reward submit [all]` -- async task (replaces Sidekiq job), calls `EqdkpClient.create_reward_adjustment`
- `/reward status` -- pending rewards embeds
- `/reward report <id_or_character>` -- lookup by reward ID or character name
- `/reward remove <reward_id>` -- delete reward row

### Config Additions
```ini
[raid]
reward_server_id = 789012

[eqdkp]
reward_adjustment_event_id = ...
```

### Google Sheets Reload
The `/reload cheevos` subcommand should upsert the `cheevos` table from the Google Sheets "cheevos" tab. This is part of `cmd_reload.py` and should be included when rewards are enabled.

### EQdkp Client Method
`EqdkpClient.create_reward_adjustment(character, dkp, reason, time)` -- already planned as part of `eqdkp/client.py`. Posts to `/api.php?function=add_adjustment` with `REWARD_ADJUSTMENT_EVENT_ID`.

### Permission Gates
Uses the same `can(member, permission)` system:
- `:reward` -- give a reward
- `:submit` -- submit rewards to EQdkp (on reward server context)
- `:reward_report` -- view reward reports
- `:remove_reward` -- delete reward records
