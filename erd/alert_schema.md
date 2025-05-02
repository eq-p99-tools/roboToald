# RoboToald Alert Database Schema

## Tables and Relationships

### 1. Alert
- **Description**: Represents user-defined alerts for monitoring channel messages
- **Columns**:
  - `id` (Integer, Primary Key)
  - `channel_id` (Integer)
  - `user_id` (Integer)
  - `alert_regex` (String(255))
  - `alert_role` (Integer)
  - `alert_url` (String(100))
  - `trigger_count` (Integer)
  - `guild_id` (Integer)
- **Indexes**:
  - Unique Constraint on (`user_id`, `channel_id`, `alert_regex`, `alert_url`)

## Entity Relationship Diagram

The Alert schema consists of a single table. Please refer to the [Alert ERD](./alert_erd.svg) for a visual representation.

## Key Database Operations

1. **Alert Management**:
   - Users can create, update, and delete alerts
   - Alerts are tied to specific channels and users
   - Each alert has a regex pattern to match against messages

2. **Alert Triggering**:
   - When a message matches an alert's regex pattern, the alert is triggered
   - The system can notify users or roles when alerts are triggered
   - The `trigger_count` tracks how many times an alert has been activated

3. **Alert Querying**:
   - Alerts can be queried by user, channel, or guild
   - Multiple helper functions exist for retrieving alerts based on different criteria

## Implementation Notes

The Alert model inherits from both `base.Base` (SQLAlchemy declarative base) and `base.MyBase` (custom base class with helper methods). This provides additional functionality for querying and managing alerts beyond basic ORM operations.

## Usage Examples

Alerts are typically used to notify users when specific keywords or patterns appear in Discord channels. For example:

- Monitoring for raid announcements in an MMO
- Tracking when specific items are mentioned in a marketplace channel
- Notifying when certain events are scheduled or discussed
