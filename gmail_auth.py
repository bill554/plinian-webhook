from __future__ import print_function
import os.path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
import json

SCOPES = ['https://www.googleapis.com/auth/gmail.compose']

def main():
    creds = None
    if os.path.exists('token.json'):
        print("token.json already exists — done!")
        return

    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)

    # Save the credentials to token.json
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
        print("✅ token.json generated!")

if __name__ == '__main__':
    main()
