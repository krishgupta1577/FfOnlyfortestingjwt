from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
import binascii
import aiohttp
import requests
import json
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

async def send_multiple_requests(uid, server_name, url, likes_limit=None):
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

        # /setlikes se aaya limit apply karo (sirf utne JWT use honge)
        if likes_limit is not None and likes_limit > 0:
            valid_tokens = valid_tokens[:likes_limit]
            app.logger.info(f"Using limited tokens: {len(valid_tokens)} (limit={likes_limit})")

        # NAYA FIX: Rate Limiting Bypass (429 Error rokne ke liye)
        semaphore = asyncio.Semaphore(300)

        async def bounded_send(token):
            async with semaphore:
                await asyncio.sleep(1) # Har request ke beech chhota gap
                return await send_request(encrypted_uid, token, url)

        # Har token se 1 like request (limit ke hisaab se)
        tasks = []
        for token in valid_tokens:
            tasks.append(bounded_send(token))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
        
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
            asyncio.run(send_multiple_requests(uid, server_name, url, likes_limit=likes_limit))

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
    app.run(debug=True, use_reloader=False)
