import json
import time
import asyncio
import httpx
import subprocess
import os

# --- Settings ---
# Enter the API URL here (Updated to duck API)
API_URL = "add_your_jwt_api" 
# Number of retries
MAX_RETRIES = 2 
# Delay between retries (in seconds)
RETRY_DELAY = 60 

# --- Token Generation Logic ---

async def generate_single_token(client, uid: str, password: str):
    """Generates a token from the API."""
    try:
        url = f"{API_URL}?uid={uid}&password={password}"
        resp = await client.get(url, timeout=30)
        
        # Return JSON data if the request is successful
        if resp.status_code == 200:
            return resp.json()
        # Return None if unsuccessful
        return None
    except Exception as e:
        # Print error in case of any exception
        print(f"Error for UID {uid}: {e}")
        return None

async def process_account_with_retry(client, account, index):
    """Processes an account with retry logic."""
    uid = account['uid']
    password = account['password']
    
    # Try up to the number specified in MAX_RETRIES
    for attempt in range(MAX_RETRIES):
        token_data = await generate_single_token(client, uid, password)
        
        # If token data is found, return it
        if token_data and "token" in token_data:
            return {
                "status": "success",
                "account": account,
                "token_data": token_data,
                "index": index
            }
        
        # If this is not the last attempt, wait and try again
        if attempt < MAX_RETRIES - 1:
            print(f"UID #{index + 1} {uid} - Failed. Retrying in {RETRY_DELAY} seconds...")
            await asyncio.sleep(RETRY_DELAY)
            
    # Return failure message if all attempts fail
    return {
        "status": "failed",
        "account": account,
        "index": index
    }

async def main():
    """Main function that runs the entire process."""
    input_file = "accounts.json"
    
    # If accounts.json doesn't exist, create it automatically (to prevent crashes)
    if not os.path.exists(input_file):
        print(f"⚠️ '{input_file}' not found! Creating an empty file...")
        with open(input_file, 'w') as f:
            json.dump([], f)
            
    try:
        with open(input_file) as f:
            accounts = json.load(f)
    except json.JSONDecodeError:
        print(f"Error: '{input_file}' is not a valid JSON or is empty.")
        return

    print(f"🚀 Starting token generation for {len(accounts)} accounts...")
    start_time = time.time()
    
    # Dictionary to store tokens based on region
    result = {'IND': [], 'BR': [], 'BD': []}
    failed_accounts = []
    
    # NEW LOGIC: List to store accounts that failed or have empty tokens
    failed_accounts_data = [] 

    # Send all requests concurrently using httpx.AsyncClient
    if accounts:
        async with httpx.AsyncClient() as client:
            # Create tasks for all accounts
            tasks = [process_account_with_retry(client, acc, i) for i, acc in enumerate(accounts)]
            
            # Wait for all tasks to complete
            responses = await asyncio.gather(*tasks)

            for res in responses:
                if res['status'] == 'success':
                    account = res['account']
                    token_data = res['token_data']
                    
                    # Get token value (default to empty string if missing)
                    token_val = token_data.get('token', '').strip()
                    
                    # NEW LOGIC: Check if token is actually generated (not empty)
                    if token_val:
                        raw_region = token_data.get('region', token_data.get('notiRegion', ''))
                        region_code = (raw_region if raw_region else '').upper()
                        
                        if region_code == 'IND':
                            region = 'IND'
                        elif region_code in {'BR', 'US', 'SAC', 'NA'}:
                            region = 'BR'
                        else:
                            region = 'BD'
                        
                        result[region].append({
                            'uid': account['uid'],
                            'token': token_val
                        })
                        print(f"✅ UID #{res['index'] + 1} {account['uid']} - Token generated ({region})")
                    else:
                        # NEW LOGIC: Token is empty ''
                        failed_accounts.append(account['uid'])
                        failed_accounts_data.append({
                            'uid': account['uid'],
                            'token': ''
                        })
                        print(f"⚠️ UID #{res['index'] + 1} {account['uid']} - Token is empty (Moved to failed).")
                else:
                    # Failed entirely
                    failed_accounts.append(res['account']['uid'])
                    failed_accounts_data.append({
                        'uid': res['account']['uid'],
                        'token': ''
                    })
                    print(f"❌ UID #{res['index'] + 1} {res['account']['uid']} - Failed to generate token.")

    # Save resulting tokens to regional files (Only valid tokens)
    for region in ['IND', 'BR', 'BD']:
        tokens = result[region]
        filename = f'token_{region.lower()}.json'
        
        # Creates an empty file [] even if there is no data, to prevent Git crashes
        with open(filename, 'w') as f:
            json.dump(tokens, f, indent=2)
        print(f"💾 {len(tokens)} valid tokens saved in {filename}.")

    # NEW LOGIC: Save failed/empty tokens to token_not.json
    with open('token_not.json', 'w') as f:
        json.dump(failed_accounts_data, f, indent=2)
    print(f"💾 {len(failed_accounts_data)} empty/failed accounts saved in token_not.json.")

    # --- Git Upload / Add Logic ---
    print("\n🚀 Preparing files for GitHub upload (Git Add)...")
    try:
        # This command will forcefully add files to Git, including the new token_not.json
        subprocess.run(["git", "add", "token_ind.json", "token_br.json", "token_bd.json", "token_not.json"], check=True)
        print("✅ Files successfully added to Git! Your Action will now upload them easily.")
    except Exception as e:
        print(f"⚠️ Error adding to Git (ignore this if running on a local PC): {e}")

    # --- Print detailed summary ---
    total_time = time.time() - start_time
    print("\n" + "="*40)
    print("✨ Process completed! ✨")
    print(f"⏱️ Total time: {total_time:.2f} seconds")
    print(f"📊 Total accounts: {len(accounts)}")
    print(f"✔️ Successful tokens: {len(accounts) - len(failed_accounts)}")
    print(f"❌ Failed/Empty accounts: {len(failed_accounts)}")
    if failed_accounts:
        print(f"   -> Failed UIDs: {', '.join(failed_accounts)}")
    print("="*40)


# --- Run the script ---
if __name__ == "__main__":
    # You will need the `httpx` library to run this script.
    # Install it using the command `pip install httpx`.
    asyncio.run(main())
