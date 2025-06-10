# RoboToald Discord Bot

**WARNING:** 95% of the documentation in this README is AI generated (including the ERD SVGs), so only trust it as much as you trust any AI generated documentation.

RoboToald is a Discord bot designed to enhance guild management and gaming experiences with event point tracking, raid alerts, raid-window tracking subscriptions, basic timers, and single sign-on capabilities.

## Key Features

### Single Sign-On (SSO) System
- Secure account management for game accounts
- Role-based access control with group permissions
- API authentication with encrypted credentials
- Audit logging
- Rate limiting to prevent brute force attacks

### Points System
- Track points earned and spent by users
- Award points for participation and activities
- Complete audit trail of all point transactions
- Balance calculation and reporting

### Alerts (BatPhones)
- Create custom alerts with regex pattern matching
- Get notified when specific content appears in channels
- Assign roles to be notified for specific alerts
- Track trigger counts for analytics

### Timers
- Create one-time or repeating timers
- Channel-specific or user-specific notifications
- Customizable countdown timers for events

### Raid-Window Subscriptions
- Receive notifications when a raid window opens
- Get notified before subscriptions expire
- Customizable lead times for notifications

## Documentation

### API Documentation
For details on the REST API that provides SSO authentication, see [README_API.md](README_API.md).

### Database Schema Documentation
The bot uses several database models to store and manage data. Each model has its own documentation and Entity Relationship Diagram (ERD):

- [SSO Schema](erd/sso_schema.md) - Single Sign-On system ([ERD](erd/sso_erd.svg))
- [Points Schema](erd/points_schema.md) - Points tracking system ([ERD](erd/points_erd.svg))
- [Alert (BatPhone) Schema](erd/alert_schema.md) - Alert (BatPhone) monitoring system ([ERD](erd/alert_erd.svg))
- [Timer Schema](erd/timer_schema.md) - Timer notification system ([ERD](erd/timer_erd.svg))
- [Raid-Window Subscription Schema](erd/subscription_schema.md) - Raid-window subscription tracking system ([ERD](erd/subscription_erd.svg))

## Setup and Configuration

The bot can be run standalone or with Docker using the provided Dockerfile and docker-compose.yml. Configuration is handled in `batphone.ini`.

## Security

- All passwords and sensitive data are stored encrypted
- The API server supports TLS for secure communication
- Comprehensive audit logging tracks all authentication attempts
- Rate limiting prevents brute force attacks

## Contributing

When contributing to this project, please ensure that you update the appropriate schema documentation and ERDs when making changes to the database models.
