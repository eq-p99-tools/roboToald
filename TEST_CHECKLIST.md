# Batphone-Bot Port — Test Checklist

## /rte (Tracking Channel)

- `/rte start role character target` — starts RTE, posts in channel, sends DM with X reaction
- `/rte start` with `on_character` — same but with alt character
- `/rte unrte character target` — ends RTE, message includes role/duration/DKP/ID, replies to original
- `/rte status` — embed grouped by target then role, shows duration and ID
- `/rte pending` — embed grouped by target then character, filters out 0-DKP linked chars
- `/rte submit target` — submits adjustments to EQdkp, records adjustment_id
- **DM X reaction** — clicking X on the RTE DM ends the tracking, posts summary to DM and tracking channel
- **+/- time messages** in tracking channel — adjusts tracking start/end times

## /event (Event Channels)

- `/event create target` — creates event channel with loot table, closes active RTE for target
- `/event target target_name` — sets/changes the target for an event channel
- `/event kill` — marks target as killed
- `/event nokill` — marks target as not killed
- `/event dkp value` — sets custom DKP value
- `/event status` — full raid status embed (attendees, trackers, FTEs, removals, loot, event review with Eastern time + ago)
- `/event submit` — submits raid + attendance + loot to EQdkp
- `/event submit_reset` — clears EQdkp IDs for resubmission
- `/event delete` — deletes event channel
- `/event clear` — clears attendees/loot/RTE for the event
- `/event targets` — lists all targets with aliases, DKP values, chunked embed
- `/event reorder` — repacks event channels across categories
- **+Player messages** in event channel — adds attendee(s) from `+Name` or `+Name (reason)`
- **-Player messages** in event channel — removes attendee(s)
- **Log paste** in event channel — parses EQ log lines to add attendees
- **@everyone batphone** in batphone channel — triggers batphone notification

## /loot (Event Channels)

- `/loot add item character dkp` — records loot for a character
- `/loot remove loot_id` — removes a loot record

## /fte (Event Channels)

- `/fte add character` — awards FTE DKP
- `/fte remove fte_id` — removes an FTE award

## /history (Any Channel)

- `/history character name` — shows DKP (rounded), attendance, loot history embed
- `/history character name` with ambiguous match — shows "multiple characters" list
- `/history character name` with no eqdkp user — falls through to item search
- `/history item name` — shows item loot history with 60-day avg
- **Autocomplete** on character name

## /reload

- `/reload` — reloads config from Google Sheets, shows success/error

## /register

- `/register` — registers for Pushsafer notifications

## Autocomplete Verification

- `/rte start` — target autocomplete (can_rte targets only), character autocomplete
- `/rte unrte` — target + character autocomplete
- `/rte submit` — target autocomplete
- `/event create` — target autocomplete (all targets)
- `/event target` — target autocomplete
- `/loot add` — character autocomplete
- `/fte add` — character autocomplete
- `/history character` — character autocomplete

## Permissions

- Commands requiring `submit` perm: `/rte submit`, `/event submit`
- Commands requiring `targets` perm: `/event targets`
- Commands requiring `reorder` perm: `/event reorder`
- Unpermitted users get `- No permission.` (ephemeral)

## Response Behavior

- Error messages are ephemeral where appropriate
- Deferred commands (`/event submit`, `/rte submit`, `/event status`, `/rte start`, `/reload`) complete properly (no stuck "thinking")
- `/event targets` and `/history` responses are ephemeral

