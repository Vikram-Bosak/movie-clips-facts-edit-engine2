import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']

def main():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Load client_secrets.json to start auth flow
            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secrets.json', SCOPES)
            # Use local server on allowed port 8080 to match client_secrets.json
            creds = flow.run_local_server(port=8080, open_browser=False)
            
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            
    print("Authentication successful! token.json has been written.")

if __name__ == '__main__':
    main()
