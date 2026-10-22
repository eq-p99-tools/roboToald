# Raid Timers Database Schema

> **Note:** This documentation is primarily AI-generated from the source code and may contain inaccuracies. Always verify behavior against the actual implementation.

Source: `roboToald/db/models/raid_timers.py`

## Entity Relationship Diagram

```mermaid
erDiagram
    RtTarget ||--o{ RtRespawnRange : ranges
    RtTarget ||--o{ RtTod : tods
    RtTarget {
        int id PK
        int guild_id
        string name
        string short_name
        string aliases
        string era
        string zone
        bool hidden
        int window_count
        bool quake_immune
        string note
        string seed_key
        bool customized
    }
    RtRespawnRange {
        int id PK
        int target_id FK
        int min_minutes
        int max_minutes
    }
    RtTod {
        int id PK
        int guild_id
        int target_id FK
        int tod_utc
        string source
        string reported_by
        int created_at
    }
    RtQuake {
        int id PK
        int guild_id
        int quake_utc
        string source
        string reported_by
        int created_at
    }
    RtBoardMessage {
        int guild_id PK
        int channel_id
        string message_ids
    }
```

## Behavior

- Per-guild copy of the default P99 catalog (`roboToald/raidtargets/data/p99_targets_default.json`).
- Current ToD = highest `rt_tods.id` for `(guild_id, target_id)`.
- Last quake = highest `rt_quakes.id` for the guild.
- Window math: `roboToald/raidtargets/rt_windows.py` (PHP `targets-v2.json` port).
