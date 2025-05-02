# RoboToald Timer Database Schema

## Tables and Relationships

### 1. Timer
- **Description**: Represents scheduled timers that can trigger notifications
- **Columns**:
  - `id` (String(8), Primary Key)
  - `channel_id` (Integer)
  - `user_id` (Integer)
  - `name` (String(100))
  - `seconds` (Integer)
  - `first_run` (Integer)
  - `next_run` (Integer)
  - `repeating` (Boolean)
  - `guild_id` (Integer)

## Entity Relationship Diagram

Please refer to the [Timer ERD](./timer_erd.svg) for a visual representation of this table.

## Key Database Operations

1. **Timer Management**:
   - Users can create, update, and delete timers
   - Timers can be one-time or repeating
   - Each timer is associated with a specific channel, user, and guild

2. **Timer Scheduling**:
   - The `first_run` field tracks when the timer was initially set
   - The `next_run` field determines when the timer will trigger next
   - For repeating timers, the `next_run` is updated after each trigger

3. **Timer Querying**:
   - Timers can be queried by ID, user, channel, or guild
   - Helper functions exist for retrieving timers based on different criteria:
     - `get_timer(timer_id)`: Get a specific timer by ID
     - `get_timers()`: Get all timers across all users and channels
     - `get_timers_for_channel(channel_id)`: Get all timers for a specific channel
     - `get_timers_for_user(user_id, guild_id)`: Get all timers for a specific user
     - `get_timers_for_user_in_channel(user_id, channel_id)`: Get all timers for a specific user in a specific channel

## Implementation Notes

The Timer model uses a string ID rather than an auto-incrementing integer, allowing for more readable timer identifiers. The `__use_quota__` attribute indicates that timers are subject to quota limitations, preventing users from creating too many timers.

The model includes both the original configuration (`seconds`, `first_run`) and the runtime state (`next_run`), making it easy to reset or recalculate timers as needed.

## Usage Examples

Timers are typically used for:

- Reminding users about scheduled events
- Tracking cooldowns for in-game activities
- Setting up recurring notifications
- Creating countdown timers for important deadlines

The repeating functionality allows for creating both one-time alerts and regular scheduled reminders.
