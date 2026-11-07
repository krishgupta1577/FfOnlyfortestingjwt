from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
import time
import like_pb2
import like_count_pb2
import uid_generator_pb2
from google.protobuf.message import DecodeError

app = Flask(__name__)

def load_tokens(server_name):
    try:
        if server_name == "IND":
            with open("token_ind.json", "r") as f:
                tokens = json.load(f)
        elif server_name in {"BR", "US", "SAC", "NA"}:
            with open("token_br.json", "r") as f:
                tokens = json.load(f)
        else:
            with open("token_bd.json", "r") as f:
                tokens = json.load(f)
        return tokens
    except Exception as e:
        app.logger.error(f"Error loading tokens for server {server_name}: {e}")
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

async def send_multiple_requests(uid, server_name, url, likes_limit=None, before_like=0):
    """Send like requests until the ACTUAL target is reached.

    likes_limit is an actual likes target (for example /setlikes 9 means
    try to add 9 real likes). It is NOT a JWT count. If the first 9 JWTs do
    not produce 9 likes, additional JWTs from the saved token file are used
    until the target is reached or all available JWTs are exhausted.
    """
    try:
        region = server_name
        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            app.logger.error("Failed to create protobuf message.")
            return None

        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            app.logger.error("Encryption failed.")
            return None

        tokens = load_tokens(server_name)
        if tokens is None or len(tokens) == 0:
            app.logger.error("Failed to load tokens or token list is empty.")
            return None

        valid_tokens = []
        for t in tokens:
            t_val = t.get("token", "").strip().replace('\n', '').replace('\r', '').replace(' ', '')
            if t_val:
                valid_tokens.append(t_val)

        if not valid_tokens:
            app.logger.error("No valid tokens found in the loaded JSON.")
            return None

        target = int(likes_limit) if likes_limit is not None else None
        current_likes = int(before_like or 0)
        target_likes = current_likes + target if target and target > 0 else None
        jwt_used = 0
        successful_requests = 0
        # Vercel-safe deadline: return a JSON result instead of hanging until the platform kills the function.
        deadline = time.monotonic() + 45

        app.logger.info(
            f"Like target: {target if target else 'ALL'} | "
            f"Starting likes: {current_likes} | Available JWTs: {len(valid_tokens)}"
        )

        # One JWT at a time. After every request, check the real like count.
        # This allows the API to consume extra JWTs when some JWTs give 0 likes.
        for index, token in enumerate(valid_tokens, start=1):
            if time.monotonic() >= deadline:
                app.logger.warning("Execution safety deadline reached; returning current progress.")
                break
            if target_likes is not None and current_likes >= target_likes:
                app.logger.info(
                    f"Target reached: {current_likes}/{target_likes}. "
                    f"Stopping after {jwt_used} JWT(s)."
                )
                break

            jwt_used += 1
            try:
                await asyncio.sleep(0.15)
                result = await send_request(encrypted_uid, token, url)
                successful_requests += 1

                if isinstance(result, int):
                    app.logger.warning(
                        f"JWT {index}/{len(valid_tokens)} failed with HTTP {result}. "
                        f"Trying next JWT."
                    )
                    continue

                # Check actual likes immediately after this JWT.
                try:
                    after = make_request(encrypted_uid, server_name, token)
                    if after is not None:
                        jsone = MessageToJson(after)
                        data_after = json.loads(jsone)
                        new_likes = int(data_after.get('AccountInfo', {}).get('Likes', 0))
                        app.logger.info(
                            f"JWT {index}: likes {current_likes} -> {new_likes}"
                        )
                        current_likes = new_likes
                    else:
                        app.logger.warning(
                            f"JWT {index}: like request sent, but profile check returned no data."
                        )
                except Exception as check_error:
                    app.logger.warning(
                        f"JWT {index}: profile check failed: {check_error}. "
                        f"Trying next JWT."
                    )

            except Exception as request_error:
                app.logger.warning(
                    f"JWT {index}/{len(valid_tokens)} request error: {request_error}. "
                    f"Trying next JWT."
                )

        target_reached = bool(target_likes is not None and current_likes >= target_likes)
        if target_likes is not None:
            app.logger.info(
                f"Final target result: {current_likes - int(before_like or 0)} "
                f"likes gained | Target: {target} | JWTs used: {jwt_used}/{len(valid_tokens)} | "
                f"Reached: {target_reached}"
            )

        return {
            "likes_before": int(before_like or 0),
            "likes_after": current_likes,
            "likes_given": max(0, current_likes - int(before_like or 0)),
            "target": target,
            "target_reached": target_reached if target is not None else None,
            "jwt_used": jwt_used,
            "available_jwts": len(valid_tokens),
            "successful_requests": successful_requests,
        }

    except Exception as e:
        app.logger.error(f"Exception in send_multiple_requests: {e}")
        return None


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
        
        response = requests.post(url, data=edata, headers=headers, verify=False, timeout=(4, 8))
        
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

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "ok", "service": "Free Fire Like API", "usage": "/like?uid=<UID>&server_name=<REGION>&likes=<TARGET>"}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

@app.route('/like', methods=['GET'])
def handle_requests():
    uid = request.args.get("uid")
    server_name = request.args.get("server_name", "").upper()
    if not uid or not uid.isdigit() or len(uid) > 20:
        return jsonify({"error": "Valid numeric UID is required"}), 400
    allowed_regions = {"IND", "BR", "US", "SAC", "NA", "BD"}
    if server_name not in allowed_regions:
        return jsonify({"error": f"Unsupported server_name: {server_name}"}), 400
    # Bot ke /setlikes se aane wala limit (optional)
    likes_param = request.args.get("likes")
    likes_limit = None
    if likes_param:
        try:
            likes_limit = int(likes_param)
            if likes_limit < 1:
                likes_limit = None
        except ValueError:
            likes_limit = None
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

            # Like bhejne ka process
            send_result = asyncio.run(
                send_multiple_requests(
                    uid, server_name, url,
                    likes_limit=likes_limit,
                    before_like=before_like
                )
            )

            # Final profile check. If it fails, use the last verified count
            # returned by send_multiple_requests instead of turning a successful
            # like run into HTTP 500.
            after = None
            try:
                after = make_request(encrypted_uid, server_name, working_token)
            except Exception as e:
                app.logger.warning(f"Final after-profile check failed: {e}")

            player_uid = int(uid)
            player_name = ""
            player_region = server_name
            player_level = ""

            if after is not None:
                try:
                    jsone_after = MessageToJson(after)
                    data_after = json.loads(jsone_after)
                    after_like = int(data_after.get('AccountInfo', {}).get('Likes', 0))
                    player_uid = int(data_after.get('AccountInfo', {}).get('UID', uid))
                    player_name = str(data_after.get('AccountInfo', {}).get('PlayerNickname', ''))
                    player_region = str(data_after.get('AccountInfo', {}).get('region', server_name))
                    player_level = str(data_after.get('AccountInfo', {}).get('level', ''))
                except Exception as e:
                    app.logger.warning(f"Final after-profile parse failed: {e}")
                    after = None

            if after is None:
                if send_result is None:
                    raise Exception("Like process failed and final profile check was unavailable.")
                after_like = int(send_result.get("likes_after", before_like))

            like_given = max(0, after_like - before_like)
            status = 1 if like_given != 0 else 2
            result = {
                "LikesGivenByAPI": like_given,
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
    app.run(debug=False, use_reloader=False)
