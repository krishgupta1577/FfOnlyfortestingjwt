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

# ============================================================
# 🔥 OB55 CONSTANTS
# ============================================================
RELEASE_VERSION = "OB55"
X_UNITY_VERSION = "2018.4.12f1"
USER_AGENT = "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)"

# Region → Server URL map
REGION_URLS = {
    "IND": {
        "like_url": "https://client.ind.freefiremobile.com/LikeProfile",
        "profile_url": "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",
        "host": "client.ind.freefiremobile.com"
    },
    "BR": {
        "like_url": "https://client.us.freefiremobile.com/LikeProfile",
        "profile_url": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "host": "client.us.freefiremobile.com"
    },
    "US": {
        "like_url": "https://client.us.freefiremobile.com/LikeProfile",
        "profile_url": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "host": "client.us.freefiremobile.com"
    },
    "SAC": {
        "like_url": "https://client.us.freefiremobile.com/LikeProfile",
        "profile_url": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "host": "client.us.freefiremobile.com"
    },
    "NA": {
        "like_url": "https://client.us.freefiremobile.com/LikeProfile",
        "profile_url": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
        "host": "client.us.freefiremobile.com"
    },
    "BD": {
        "like_url": "https://clientbp.ggpolarbear.com/LikeProfile",
        "profile_url": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "host": "clientbp.ggpolarbear.com"
    },
    "ME": {
        "like_url": "https://clientbp.ggpolarbear.com/LikeProfile",
        "profile_url": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "host": "clientbp.ggpolarbear.com"
    },
    "PK": {
        "like_url": "https://clientbp.ggpolarbear.com/LikeProfile",
        "profile_url": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "host": "clientbp.ggpolarbear.com"
    },
    "SG": {
        "like_url": "https://clientbp.ggpolarbear.com/LikeProfile",
        "profile_url": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "host": "clientbp.ggpolarbear.com"
    },
    "ID": {
        "like_url": "https://clientbp.ggpolarbear.com/LikeProfile",
        "profile_url": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "host": "clientbp.ggpolarbear.com"
    },
    "TW": {
        "like_url": "https://clientbp.ggpolarbear.com/LikeProfile",
        "profile_url": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "host": "clientbp.ggpolarbear.com"
    },
    "TH": {
        "like_url": "https://clientbp.ggpolarbear.com/LikeProfile",
        "profile_url": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "host": "clientbp.ggpolarbear.com"
    },
    "VN": {
        "like_url": "https://clientbp.ggpolarbear.com/LikeProfile",
        "profile_url": "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow",
        "host": "clientbp.ggpolarbear.com"
    },
}


def _get_urls(server_name: str):
    """Get region URLs with fallback."""
    s = server_name.upper() if server_name else "IND"
    if s in REGION_URLS:
        return REGION_URLS[s]
    # Default to IND
    return REGION_URLS["IND"]


def _get_headers(host: str, token: str = None, payload_len: int = 0) -> dict:
    """Build OB55 headers."""
    headers = {
        "User-Agent": USER_AGENT,
        "Connection": "Keep-Alive",
        "Host": host,
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": X_UNITY_VERSION,
        "X-GA": "v1 1",
        "X-GA-SV": str(int(time.time())),
        "ReleaseVersion": RELEASE_VERSION,
    }
    if token:
        clean_token = str(token).strip().replace('\n', '').replace('\r', '').replace(' ', '')
        headers["Authorization"] = f"Bearer {clean_token}"
    if payload_len:
        headers["Content-Length"] = str(payload_len)
    return headers


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


async def send_request(encrypted_uid, token, url, host):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = _get_headers(host, token=token, payload_len=len(edata))

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers, ssl=False) as response:
                if response.status != 200:
                    error_msg = await response.text()
                    app.logger.error(f"Request failed: {response.status}, {error_msg[:100]}")
                    return response.status
                return await response.text()
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None


async def send_multiple_requests(uid, server_name, url, like_count):
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

        # 🔥 Rate limiting bypass
        semaphore = asyncio.Semaphore(300)
        host = _get_urls(server_name)["host"]

        async def bounded_send(token):
            async with semaphore:
                await asyncio.sleep(1)
                return await send_request(encrypted_uid, token, url, host)

        tasks = []
        # Send exactly the requested number of likes. Tokens are reused only
        # after every available token has been assigned once.
        for i in range(like_count):
            token = valid_tokens[i % len(valid_tokens)]
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
        urls = _get_urls(server_name)
        url = urls["profile_url"]
        host = urls["host"]

        edata = bytes.fromhex(encrypt)
        headers = _get_headers(host, token=token, payload_len=len(edata))

        response = requests.post(url, data=edata, headers=headers, verify=False, timeout=15)

        if response.status_code != 200:
            raise Exception(f"API Error! Status: {response.status_code}, Message: {response.text[:100]}")

        hex_data = response.content.hex()
        binary = bytes.fromhex(hex_data)
        decode = decode_protobuf(binary)

        if decode is None:
            raise Exception("Protobuf decode fail.")

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
        requested_tokens = int(request.args.get("likes", "20"))
    except (TypeError, ValueError):
        return jsonify({"error": "likes must be a whole number"}), 400

    if requested_tokens < 2 or requested_tokens > 400:
        return jsonify({"error": "likes must be between 2 and 400"}), 400

    # Keep one token in reserve: 20 requested tokens produce 19 like calls.
    like_count = requested_tokens - 1

    try:
        def process_request():
            tokens = load_tokens(server_name)
            if tokens is None or len(tokens) == 0:
                raise Exception("Failed to load tokens or token JSON is empty.")

            valid_tokens = [
                t.get("token", "").strip().replace('\n', '').replace('\r', '').replace(' ', '')
                for t in tokens if t.get("token", "")
            ]
            if not valid_tokens:
                raise Exception("No valid tokens found in the file.")

            encrypted_uid = enc(uid)
            if encrypted_uid is None:
                raise Exception("Encryption of UID failed.")

            # 🔥 Token fallback
            before = None
            working_token = None

            for tkn in valid_tokens:
                try:
                    before = make_request(encrypted_uid, server_name, tkn)
                    if before is not None:
                        working_token = tkn
                        break
                except Exception as e:
                    app.logger.warning(f"Token error (Skipping): {str(e)[:80]}")

            if before is None or working_token is None:
                raise Exception("All tokens failed or blocked.")

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
            app.logger.info(f"Likes before: {before_like}")

            # 🔥 Like URL
            urls = _get_urls(server_name)
            like_url = urls["like_url"]

            # Send the requested number of likes (one token remains in reserve).
            if like_count:
                asyncio.run(send_multiple_requests(uid, server_name, like_url, like_count))

            # After check
            try:
                after = make_request(encrypted_uid, server_name, working_token)
            except Exception as e:
                raise Exception(f"Likes sent, but after-profile failed: {str(e)}")

            if after is None:
                raise Exception("Likes sent but after-profile load failed.")

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
    app.run(debug=False, use_reloader=False)