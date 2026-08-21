import os
from google_auth_oauthlib.flow import InstalledAppFlow

def authenticate():
    scopes = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']
    credentials_path = "credentials.json"
    token_path = "token.json"

    if not os.path.exists(credentials_path):
        print(f"Error: {credentials_path} not found.")
        return

    print("Starting Google Drive OAuth Flow...")
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, scopes=scopes)
    
    # Run local server to complete the authorization without opening default host browser
    creds = flow.run_local_server(port=8080, prompt='consent', open_browser=False)
    
    # Save the credentials to token.json for future use
    with open(token_path, "w") as token_file:
        token_file.write(creds.to_json())
    
    print(f"Authentication successful! Credentials saved to {token_path}")

if __name__ == "__main__":
    authenticate()
