# Lab Schedule OAuth Setup Guide

## Google OAuth Configuration

This application uses Google OAuth 2.0 for authentication. Users must sign in with an `@aucklanduni.ac.nz` email address.

### Prerequisites

1. Google Cloud Account
2. GCP Project with Google+ API enabled

### Setup Steps

#### 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown and select "NEW PROJECT"
3. Enter project name: "Lab Schedule"
4. Click "CREATE"

#### 2. Enable Google+ API

1. In the Cloud Console, search for "Google+ API"
2. Click on "Google+ API"
3. Click "ENABLE"

#### 3. Create OAuth 2.0 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click "CREATE CREDENTIALS" → "OAuth Client ID"
3. Choose "Web application"
4. Set up the consent screen if prompted:
   - User type: Internal
   - Required fields: App name, User support email, Developer contact
5. Under "Authorized redirect URIs", add:
   - `http://localhost:8080/auth/callback` (for local development)
   - `https://yourdomain.com/auth/callback` (for production)

#### 4. Configure Environment Variables

1. Copy the credentials JSON:
   - Client ID
   - Client Secret
   - Redirect URI

2. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

3. Edit `.env` with your credentials:
   ```
   GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your_client_secret
   GOOGLE_REDIRECT_URI=http://localhost:8080/auth/callback
   GOOGLE_HOSTED_DOMAIN=aucklanduni.ac.nz
   # Optional: prefill a specific Auckland account in Google’s login screen
   # GOOGLE_LOGIN_HINT=student.name@aucklanduni.ac.nz
   # Local development only: required when using a localhost HTTP callback
   # OAUTHLIB_INSECURE_TRANSPORT=1
   APP_SECRET_KEY=generate-a-random-secret-key
   ```

   The Google consent redirect uses the `aucklanduni.ac.nz` hosted-domain hint, and if `GOOGLE_LOGIN_HINT` is set it will prefill that account in the third-party login screen.

#### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

#### 6. Run the Application

```bash
python main.py
```

The application will start at `http://localhost:8080`.

### User Flow

1. User lands on the login page
2. Clicks "Sign in with Google"
3. Authenticates with Google account
4. System verifies email ends with `@aucklanduni.ac.nz`
5. User account created/updated in database
6. User redirected to main app with session token

### Security Notes

- Never commit `.env` file to version control (use `.env.example`)
- Change `APP_SECRET_KEY` in production to a strong random value
- For production, use HTTPS and secure session handling
- Consider implementing proper JWT tokens instead of simple UUID tokens
- Implement CSRF protection for OAuth flows
- Use secure HTTP-only cookies for session management

### Troubleshooting

**"Only aucklanduni.ac.nz email addresses are allowed"**
- User is not signed in with an @aucklanduni.ac.nz email
- Check that the Google account has the correct email domain

**"Google OAuth not configured"**
- Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in .env
- Check that .env file exists and variables are set correctly

**Redirect URI mismatch**
- Ensure GOOGLE_REDIRECT_URI in .env matches the authorized redirect URI in GCP console
- For localhost development: `http://localhost:8080/auth/callback`
