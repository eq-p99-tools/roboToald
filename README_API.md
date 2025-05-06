# RoboToald REST API

This extension adds a REST API server to RoboToald for the P99 Login Proxy SSO system, allowing authentication through the SSO database.

## Features

- Provides an authentication endpoint for SSO accounts
- Comprehensive audit logging of all authentication attempts
- Rate limiting to prevent brute force attacks

## API Usage

The API server can run using TLS or not, depending on configuration. If running without TLS, a reverse-proxy is recommended to ensure secure traffic.

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

### List Accounts Endpoint

**URL**: `/list_accounts`  
**Method**: `POST`  
**Content-Type**: `application/json`

**TODO:** document this

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

- IP addresses with more than some number of failed authentication attempts within a rolling time period are temporarily blocked
- Blocked IPs receive a 429 Too Many Requests response with a message to try again later
- All rate limiting events are recorded in the audit log
