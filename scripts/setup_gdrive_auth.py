"""
POPCONE CRM - Google Drive OAuth 2.0 Setup Utility
---------------------------------------------------
This interactive CLI script generates a long-lived refresh token for your personal
Google account using Google Drive's free tier (15 GB personal quota).
No billing or paid services are required.

Scope requested:
- 'https://www.googleapis.com/auth/drive.file'
  Restricted to files and folders created by this CRM application only.
  Zero access to any other files in your Google Drive.

Instructions:
1. Open Google Cloud Console: https://console.cloud.google.com/
2. Create a new project: e.g. 'Popcone-CRM-Backups' (100% free)
3. Navigate to 'APIs & Services' -> 'Library' -> Search for 'Google Drive API' -> Click 'Enable'
4. Navigate to 'OAuth consent screen':
   - User Type: External
   - App Name: Popcone CRM Backups
   - Support email: your email
   - Scopes: add '.../auth/drive.file'
   - Test users: add your own Gmail address
   - Save and continue
5. Navigate to 'Credentials' -> 'Create Credentials' -> 'OAuth client ID':
   - Application type: 'Desktop app' (or 'Web application' with redirect URI http://localhost:8080/)
   - Name: 'Popcone CRM Client'
   - Click 'Create'
   - Copy Client ID and Client Secret
6. Run this script:
   python scripts/setup_gdrive_auth.py
"""

import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Error: google-auth-oauthlib is not installed.")
    print("Run: pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def main():
    print("=" * 65)
    print(" POPCONE CRM - GOOGLE DRIVE OAUTH 2.0 SETUP (FREE TIER)")
    print("=" * 65)
    print("\nThis tool connects your personal Google Drive account to POPCONE CRM")
    print("using the restricted 'drive.file' scope (access only to backups created by this app).\n")

    client_id = input("Enter your OAuth Client ID: ").strip()
    client_secret = input("Enter your OAuth Client Secret: ").strip()

    if not client_id or not client_secret:
        print("\nError: Client ID and Client Secret are required.")
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/", "urn:ietf:wg:oauth:2.0:oob"]
        }
    }

    try:
        flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
        # Attempt local server flow on port 8080 or port 0
        try:
            creds = flow.run_local_server(port=8080, prompt="consent", access_type="offline")
        except Exception:
            # Fallback to console prompt
            creds = flow.run_console()

        refresh_token = creds.refresh_token
        if not refresh_token:
            print("\nWarning: Google did not return a refresh_token.")
            print("Make sure you specified prompt='consent' and access_type='offline'.")
            print("To force consent, remove the app at: https://myaccount.google.com/permissions")
            sys.exit(1)

        print("\n" + "=" * 65)
        print(" SUCCESS! AUTHENTICATION COMPLETED")
        print("=" * 65)
        print("\nAdd the following lines to your local .env file and your")
        print("Vercel Project Settings -> Environment Variables:\n")
        print(f"GDRIVE_CLIENT_ID={client_id}")
        print(f"GDRIVE_CLIENT_SECRET={client_secret}")
        print(f"GDRIVE_REFRESH_TOKEN={refresh_token}")
        print("\n(Never commit these credentials into git or share them publicly.)\n")

    except Exception as e:
        print(f"\nAuthentication failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
