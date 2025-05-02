# RoboToald Subscription Database Schema

## Tables and Relationships

### 1. Subscription
- **Description**: Represents user subscriptions to various targets with expiry tracking
- **Columns**:
  - `user_id` (Integer, Part of Primary Key)
  - `target` (String(255), Part of Primary Key)
  - `expiry` (Integer, Not Null)
  - `last_notified` (Integer, Default: 0)
  - `lead_time` (Integer, Default: 1800, Not Null)
  - `last_window_start` (Integer, Default: 0)
  - `guild_id` (Integer, Not Null)
- **Indexes**:
  - Primary Key Constraint: `pk_user_id_target` on (`user_id`, `target`)

## Entity Relationship Diagram

Please refer to the [Subscription ERD](./subscription_erd.svg) for a visual representation of this table.

## Key Database Operations

1. **Subscription Management**:
   - Users can create, update, and delete subscriptions to various targets
   - Each subscription is uniquely identified by the combination of user_id and target
   - Subscriptions are associated with specific guilds

2. **Expiry Tracking**:
   - The system tracks when subscriptions expire using the `expiry` field
   - Users can be notified before expiry based on the `lead_time` setting
   - The `last_notified` field prevents duplicate notifications

3. **Notification Windows**:
   - The `last_window_start` field helps manage notification periods
   - Notifications can be scheduled at appropriate intervals before expiry

## Implementation Notes

The Subscription model inherits from both `base.Base` (SQLAlchemy declarative base) and `base.MyBase` (custom base class with helper methods). This provides additional functionality for querying and managing subscriptions beyond basic ORM operations.

The composite primary key (`user_id`, `target`) ensures that a user can only have one subscription to a specific target, preventing duplicate subscriptions.

## Usage Examples

Subscriptions are typically used to track time-limited resources or events, such as:

- Game subscription renewals
- Event registrations with deadlines
- Limited-time access to resources
- Membership renewals

The system can notify users when their subscriptions are approaching expiry, allowing them to take action before access is lost.
