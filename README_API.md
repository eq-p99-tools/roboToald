# RoboToald REST API

This extension adds a standalone REST API server for the RoboToald SSO system, allowing authentication through the existing database.

## Features

- Runs independently from the Discord bot
- Provides an authentication endpoint for SSO accounts
- Uses the same database as the Discord bot
- Secure password handling
- Comprehensive audit logging of all authentication attempts
- Rate limiting to prevent brute force attacks

## Installation

1. Install the additional dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Run the API server:
   ```
   python api_server.py
   ```

## API Usage

The API server runs on port 8000 by default. The following endpoints are available:

### Authentication Endpoint

**URL**: `/auth`  
**Method**: `POST`  
**Content-Type**: `application/json`

Send a JSON object with username and password in the request body. The server will:

1. Look up the username in the SSOAccount table
2. Look up the password in the SSOAccessKey table to find the discord_user_id
3. Check if the user has access to the requested username
4. Return the real credentials if authorized

#### Example Request

```bash
curl -X POST http://localhost:8000/auth \
  -H "Content-Type: application/json" \
  -d '{"username": "username", "password": "password"}'
```

#### Success Response

```json
{
  "real_user": "actual_username",
  "real_pass": "actual_password"
}
```

#### Error Responses

- **401 Unauthorized**: Authentication failed
- **429 Too Many Requests**: Too many failed attempts (rate limited)

For security reasons, all authentication failures return the same error code and message regardless of the specific reason (invalid credentials, account not found, or access denied). This prevents information leakage about what accounts exist in the system.

## Security Considerations

- The API accepts credentials as JSON in the request body
- All authentication failures return the same generic error to prevent information leakage
- For production use, configure HTTPS to encrypt credentials in transit
- Access keys and passwords are stored encrypted in the database
- All authentication attempts are logged in the audit log
- Rate limiting blocks IPs with more than 10 failed attempts in the last hour

## Audit Logging

The system maintains a comprehensive audit log of all authentication attempts with the following information:

- Timestamp of the attempt
- Username used in the authentication attempt
- IP address of the client (when available)
- Success or failure status
- Associated Discord user ID (when available)
- Associated account ID and guild ID (when available)
- Detailed reason for failures

The audit log can be queried from the database for security monitoring and compliance purposes.

## Rate Limiting

To protect against brute force attacks, the API implements rate limiting with the following behavior:

- IP addresses with more than 10 failed authentication attempts within the last hour are temporarily blocked
- Blocked IPs receive a 429 Too Many Requests response with a message to try again later
- All rate limiting events are recorded in the audit log
- The rate limit counter resets automatically after one hour from each failed attempt
