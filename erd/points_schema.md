# RoboToald Points Database Schema

## Tables and Relationships

### 1. PointsAudit
- **Description**: Tracks point-related events for users in a guild
- **Columns**:
  - `id` (Integer, Primary Key, Auto-increment)
  - `user_id` (Integer)
  - `guild_id` (Integer)
  - `event` (Enum(Event))
  - `time` (DateTime)
  - `active` (Boolean, Default: True)
  - `start_id` (Integer, Nullable)
- **Relationships**:
  - Self-referential relationship: `start_id` can reference another `PointsAudit.id`

### 2. PointsEarned
- **Description**: Records points awarded to users
- **Columns**:
  - `id` (Integer, Primary Key, Auto-increment)
  - `user_id` (Integer)
  - `guild_id` (Integer)
  - `points` (Integer)
  - `time` (DateTime)
  - `notes` (Text)
  - `adjustor` (Integer)

### 3. PointsSpent
- **Description**: Records points spent by users
- **Columns**:
  - `id` (Integer, Primary Key, Auto-increment)
  - `user_id` (Integer)
  - `guild_id` (Integer)
  - `points` (Integer)
  - `time` (DateTime)

## Entity Relationship Diagram

Please refer to the [Points ERD](./points_erd.svg) for a visual representation of these tables and their relationships.

## Key Database Operations

1. **Points Tracking**:
   - The system tracks points earned and spent by users
   - Points can be awarded for various activities or events
   - Points can be spent on rewards or benefits

2. **Audit Logging**:
   - All point-related events are logged in the `PointsAudit` table
   - Events are categorized using an enum type
   - Related events can be linked using the `start_id` field

3. **Balance Calculation**:
   - A user's point balance is calculated by subtracting total points spent from total points earned
   - Helper functions exist to calculate balances for specific users or guilds

4. **Event Management**:
   - The `active` flag in `PointsAudit` allows events to be deactivated without deletion
   - The `notes` field in `PointsEarned` provides context for why points were awarded
   - The `adjustor` field tracks which user awarded the points

## Common Fields

All three tables share common fields:
- `user_id`: The Discord user ID
- `guild_id`: The Discord guild (server) ID
- `time`: When the event/transaction occurred

This allows for consistent querying across the points system.

## Implementation Notes

The points system is designed to be flexible and support various reward mechanisms within Discord guilds. The separation of earned and spent points provides clear tracking of all point transactions while the audit system maintains a complete history of all point-related activities.
