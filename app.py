from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import os
from pathlib import Path
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError

app = Flask(__name__)

# Token files are read from the local tokens/ folder first.
TOKEN_DIR = Path(os.getenv("TOKEN_DIR", "tokens"))

# ✅ Valid API keys
VALID_API_KEYS = {
    "ZEXXY"  # don't change warna api or bot dono nhi chalega 
}

def _token_candidates(server_name):
    region = str(server_name).upper()
    candidates = [TOKEN_DIR / f"token_{region.lower()}.json", Path(f"token_{region.lower()}.json")]
    if region == "IND":
        candidates += [TOKEN_DIR / "token_ind.json", Path("token_ind.json")]
    elif region in {"BR", "US", "SAC", "NA"}:
        candidates += [TOKEN_DIR / "token_br.json", Path("token_br.json")]
    else:
        candidates += [TOKEN_DIR / "token_bd.json", Path("token_bd.json")]
    # Preserve order and remove duplicates.
    seen = set()
    result = []
    for p in candidates:
        key = str(p)
        if key not in seen:
            seen.add(key)
            result.append(p)
    return result

def load_tokens(server_name):
    for path in _token_candidates(server_name):
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    tokens = json.load(f)
                return tokens
        except Exception as e:
            app.logger.warning(f"Error loading token file {path}: {e}")
    app.logger.error(f"No token file found for server {server_name}")
    return None

def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Error encrypting message: {e}")
        return None

def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating protobuf message: {e}")
        return None

async def send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        
        # Long JWT Token ke cleaning ke liye 
        clean_token = str(token).strip().replace('\n', '').replace('\r', '').replace(' ', '')
        
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {clean_token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                if response.status != 200:
                    error_msg = await response.text()
                    app.logger.error(f"Request failed with status code: {response.status}, Error Details: {error_msg}")
                    return response.status
                return await response.text()
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None

async def send_multiple_requests(uid, server_name, url, target=None, full=False):
    """Send LikeProfile requests using the available JWT pool.

    Normal members: keep trying different JWTs until the requested number of
    successful requests is reached, so a target of 50 may consume 100+ JWTs
    when some JWTs fail. Never intentionally sends more than the target.

    Owner/admin/full mode: use every available valid JWT once.
    """
    try:
        region = server_name
        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            return {"error": "Failed to create protobuf message."}
        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            return {"error": "Encryption failed."}

        tokens = load_tokens(server_name)
        if not tokens:
            return {"error": "No token JSON available."}

        valid_tokens = []
        for item in tokens:
            if isinstance(item, dict):
                token = str(item.get("token", "")).strip().replace("\n", "").replace("\r", "").replace(" ", "")
                if token:
                    valid_tokens.append(token)
        if not valid_tokens:
            return {"error": "No valid JWT tokens found."}

        if full:
            max_requests = len(valid_tokens)
        else:
            try:
                target = max(1, int(target or 50))
            except (TypeError, ValueError):
                target = 50
            max_requests = None

        success_count = 0
        attempted = 0
        failed = 0
        # Sequential requests intentionally allow failed JWTs to be skipped
        # and the next JWT to be tried. A token is never reused in one run.
        for token in valid_tokens:
            if not full and success_count >= target:
                break
            attempted += 1
            try:
                result = await send_request(encrypted_uid, token, url)
                if isinstance(result, str):
                    success_count += 1
                elif result == 200:
                    success_count += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                app.logger.warning(f"JWT failed, trying next token: {e}")

        if full:
            return {
                "success_requests": success_count,
                "attempted": attempted,
                "failed": failed,
                "target": None,
                "mode": "full",
            }

        reached = success_count >= target
        return {
            "success_requests": success_count,
            "attempted": attempted,
            "failed": failed,
            "target": target,
            "reached_target": reached,
            "mode": "target",
            "error": None if reached else f"Target {target} not reached; only {success_count} successful JWT requests."
        }
    except Exception as e:
        app.logger.error(f"Exception in send_multiple_requests: {e}")
        return {"error": str(e)}

def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.uid = int(uid)
        message.value = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None

def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None
    encrypted_uid = encrypt_message(protobuf_data)
    return encrypted_uid

def make_request(encrypt, server_name, token):
    try:
        if server_name == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow"
            
        edata = bytes.fromhex(encrypt)
        
        # Token clean karna zaroori hai headers parse hone ke liye
        clean_token = str(token).strip().replace('\n', '').replace('\r', '').replace(' ', '')
        
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {clean_token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }
        
        response = requests.post(url, data=edata, headers=headers, verify=False)
        
        if response.status_code != 200:
            raise Exception(f"API Error! Status: {response.status_code}, Server Message: {response.text}")
            
        hex_data = response.content.hex()
        binary = bytes.fromhex(hex_data)
        decode = decode_protobuf(binary)
        
        if decode is None:
            raise Exception("Server ne data diya par Protobuf decode fail ho gaya.")
            
        return decode
    except Exception as e:
        raise Exception(f"make_request failed: {str(e)}")

def decode_protobuf(binary):
    try:
        items = like_count_pb2.Info()
        items.ParseFromString(binary)
        return items
    except DecodeError as e:
        app.logger.error(f"Error decoding Protobuf data: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Unexpected error during protobuf decoding: {e}")
        return None

@app.route('/like', methods=['GET'])
def handle_requests():
    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()
    if not uid or not server_name:
        return jsonify({"error": "UID and server_name are required"}), 400

    try:
        def process_request():
            tokens = load_tokens(server_name)
            if tokens is None or len(tokens) == 0:
                raise Exception("Failed to load tokens or token JSON is empty.")
                
            # Sirf valid tokens uthana
            valid_tokens = [t.get("token", "").strip().replace('\n', '').replace('\r', '').replace(' ', '') for t in tokens if t.get("token", "")]
            if not valid_tokens:
                raise Exception("No valid tokens found in the file.")
                
            encrypted_uid = enc(uid)
            if encrypted_uid is None:
                raise Exception("Encryption of UID failed.")

            # NAYA LOGIC: Token Fallback. Agar pehla block/fail ho to agla check karega.
            before = None
            working_token = None
            
            for tkn in valid_tokens:
                try:
                    before = make_request(encrypted_uid, server_name, tkn)
                    if before is not None:
                        working_token = tkn
                        break
                except Exception as e:
                    app.logger.warning(f"Token error (Skipping to next): {str(e)}")
                    
            if before is None or working_token is None:
                raise Exception("Saare tokens fail ho gaye ya block ho chuke hain. API request reject ho rahi hai.")

            try:
                jsone = MessageToJson(before)
            except Exception as e:
                raise Exception(f"Error converting 'before' protobuf to JSON: {e}")
                
            data_before = json.loads(jsone)
            before_like = data_before.get('AccountInfo', {}).get('Likes', 0)
            try:
                before_like = int(before_like)
            except Exception:
                before_like = 0
            app.logger.info(f"Likes before command: {before_like}")

            if server_name == "IND":
                url = "https://client.ind.freefiremobile.com/LikeProfile"
            elif server_name in {"BR", "US", "SAC", "NA"}:
                url = "https://client.us.freefiremobile.com/LikeProfile"
            else:
                url = "https://clientbp.ppmainecoonghj.com/LikeProfile"

            target_raw = request.args.get("target")
            full_mode = str(request.args.get("full", "0")).lower() in {"1", "true", "yes", "full"}
            target = None
            if not full_mode:
                try:
                    target = max(1, int(target_raw or 50))
                except (TypeError, ValueError):
                    target = 50

            # Normal member mode: keep trying JWTs until target successful
            # requests are reached. Full mode: use the complete JWT pool.
            send_result = asyncio.run(
                send_multiple_requests(uid, server_name, url, target=target, full=full_mode)
            )
            if not send_result or send_result.get("error") and send_result.get("success_requests", 0) == 0:
                raise Exception(send_result.get("error", "Like requests failed.") if send_result else "Like requests failed.")

            # After-check ke liye wahi token use karein jo uper pass hua tha
            try:
                after = make_request(encrypted_uid, server_name, working_token)
            except Exception as e:
                raise Exception(f"Likes chale gaye, par after-profile load me error: {str(e)}")
                
            if after is None:
                raise Exception("Likes chale gaye, par after-profile load nahi hui.")
                
            try:
                jsone_after = MessageToJson(after)
            except Exception as e:
                raise Exception(f"Error converting 'after' protobuf to JSON: {e}")
                
            data_after = json.loads(jsone_after)
            after_like = int(data_after.get('AccountInfo', {}).get('Likes', 0))
            player_uid = int(data_after.get('AccountInfo', {}).get('UID', 0))
            player_name = str(data_after.get('AccountInfo', {}).get('PlayerNickname', ''))
            player_region = str(data_after.get('AccountInfo', {}).get('region', ''))
            player_level = str(data_after.get('AccountInfo', {}).get('level', ''))
            
            like_given = after_like - before_like
            target_reached = True if full_mode else bool(send_result.get("reached_target"))
            status = 1 if target_reached and like_given != 0 else 2
            result = {
                "LikesGivenByAPI": like_given,
                "TargetLikes": target,
                "SuccessfulJWTRequests": int(send_result.get("success_requests", 0)),
                "AttemptedJWTs": int(send_result.get("attempted", 0)),
                "FailedJWTs": int(send_result.get("failed", 0)),
                "TargetReached": target_reached,
                "LikesbeforeCommand": before_like,
                "LikesafterCommand": after_like,
                "PlayerNickname": player_name,
                "PlayerRegion": player_region,
                "PlayerLevel": player_level,
                "UID": player_uid,
                "status": status
            }
            return result

        result = process_request()
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Error processing request: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
        
