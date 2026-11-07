from flask import Flask, request, jsonify
import asyncio
import os
import json
import time
import binascii

import aiohttp
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf.json_format import MessageToJson
from google.protobuf.message import DecodeError

import like_pb2
import like_count_pb2
import uid_generator_pb2

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Vercel/serverless safety: never let one upstream request hang forever.
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=5, connect=2, sock_connect=2, sock_read=4)
PROFILE_TIMEOUT = (2, 5)
MAX_RUNTIME_SECONDS = 50

REGION_LIKE_URLS = {
    "IND": "https://client.ind.freefiremobile.com/LikeProfile",
    "BR": "https://client.us.freefiremobile.com/LikeProfile",
    "US": "https://client.us.freefiremobile.com/LikeProfile",
    "SAC": "https://client.us.freefiremobile.com/LikeProfile",
    "NA": "https://client.us.freefiremobile.com/LikeProfile",
}
REGION_PROFILE_URLS = {
    "IND": "https://client.ind.freefiremobile.com/GetPlayerPersonalShow",
    "BR": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "US": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "SAC": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
    "NA": "https://client.us.freefiremobile.com/GetPlayerPersonalShow",
}
DEFAULT_LIKE_URL = "https://clientbp.ppmainecoonghj.com/LikeProfile"
DEFAULT_PROFILE_URL = "https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow"


def clean_token(token):
    return str(token).strip().replace("\n", "").replace("\r", "").replace(" ", "")


def token_file_for_region(server_name):
    if server_name == "IND":
        return "token_ind.json"
    if server_name in {"BR", "US", "SAC", "NA"}:
        return "token_br.json"
    return "token_bd.json"


def load_tokens(server_name):
    path = os.path.join(BASE_DIR, token_file_for_region(server_name))
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError("token file must contain a JSON list")
        result = []
        for item in raw:
            if isinstance(item, dict):
                value = clean_token(item.get("token", ""))
            elif isinstance(item, str):
                value = clean_token(item)
            else:
                value = ""
            if value:
                result.append(value)
        return result
    except Exception as exc:
        app.logger.error(f"Token load failed: {path}: {exc}")
        return []


def encrypt_message(plaintext):
    try:
        key = b"Yg&tc%DEuh6%Zc^8"
        iv = b"6oyZDr22E3ychjM%"
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return binascii.hexlify(cipher.encrypt(pad(plaintext, AES.block_size))).decode("utf-8")
    except Exception as exc:
        app.logger.error(f"Encryption failed: {exc}")
        return None


def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as exc:
        app.logger.error(f"Like protobuf creation failed: {exc}")
        return None


def create_profile_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.uid = int(uid)
        message.value = 1
        return message.SerializeToString()
    except Exception as exc:
        app.logger.error(f"Profile protobuf creation failed: {exc}")
        return None


def enc_profile(uid):
    data = create_profile_protobuf(uid)
    return encrypt_message(data) if data is not None else None


def decode_profile(binary):
    try:
        info = like_count_pb2.Info()
        info.ParseFromString(binary)
        return info
    except DecodeError as exc:
        app.logger.warning(f"Profile protobuf decode failed: {exc}")
        return None
    except Exception as exc:
        app.logger.warning(f"Unexpected profile decode error: {exc}")
        return None


def profile_to_dict(profile):
    data = json.loads(MessageToJson(profile))
    account = data.get("AccountInfo", {})
    return {
        "likes": int(account.get("Likes", 0) or 0),
        "uid": int(account.get("UID", 0) or 0),
        "nickname": str(account.get("PlayerNickname", "") or ""),
        "region": str(account.get("region", "") or ""),
        "level": str(account.get("level", "") or ""),
    }


def sync_profile_request(encrypted_uid, server_name, token):
    """Bounded synchronous profile lookup used only for initial/final checks."""
    url = REGION_PROFILE_URLS.get(server_name, DEFAULT_PROFILE_URL)
    headers = {
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Authorization": f"Bearer {clean_token(token)}",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.11f1",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB55",
    }
    try:
        response = requests.post(
            url,
            data=bytes.fromhex(encrypted_uid),
            headers=headers,
            timeout=PROFILE_TIMEOUT,
            verify=False,
        )
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
        return decode_profile(response.content)
    except Exception as exc:
        app.logger.warning(f"Profile request failed: {exc}")
        return None


async def send_like_batch(session, encrypted_uid, tokens, url, deadline):
    """Send a bounded batch concurrently. One JWT produces at most one request."""
    if not tokens or time.monotonic() >= deadline:
        return 0, len(tokens), []

    async def one(token):
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {clean_token(token)}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB55",
        }
        try:
            remaining = max(0.2, deadline - time.monotonic())
            timeout = aiohttp.ClientTimeout(
                total=min(4.5, remaining), connect=min(1.5, remaining), sock_connect=min(1.5, remaining), sock_read=min(3.5, remaining)
            )
            async with session.post(url, data=bytes.fromhex(encrypted_uid), headers=headers, timeout=timeout) as response:
                body = await response.text()
                return response.status == 200, response.status, body[:200]
        except Exception as exc:
            return False, None, str(exc)[:200]

    results = await asyncio.gather(*(one(t) for t in tokens), return_exceptions=False)
    success = sum(1 for ok, _, _ in results if ok)
    failed = len(results) - success
    return success, failed, results


async def send_multiple_requests(uid, server_name, url, likes_limit=None, before_like=0, working_token=None):
    """Actual-like target algorithm with bounded batches and a hard runtime limit.

    `likes_limit` means ACTUAL additional likes, never JWT count.
    A batch can never contain more JWTs than the remaining target, so it cannot
    intentionally overshoot the target under the one-request/one-like model.
    After each batch the real profile Likes value is checked.
    """
    start = time.monotonic()
    deadline = start + MAX_RUNTIME_SECONDS
    region = server_name
    protobuf = create_protobuf_message(uid, region)
    if protobuf is None:
        return {"error": "Failed to create like protobuf."}
    encrypted_uid = encrypt_message(protobuf)
    if encrypted_uid is None:
        return {"error": "Encryption failed."}

    tokens = load_tokens(server_name)
    if not tokens:
        return {"error": "Token file is empty or unavailable."}

    target = int(likes_limit) if likes_limit is not None and int(likes_limit) > 0 else None
    baseline = int(before_like)
    last_like = baseline
    attempted = 0
    success_requests = 0
    failed = 0
    checks = 0
    token_index = 0
    profile_token = working_token or tokens[0]
    like_url = url or REGION_LIKE_URLS.get(server_name, DEFAULT_LIKE_URL)

    connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector, timeout=HTTP_TIMEOUT) as session:
        while token_index < len(tokens) and time.monotonic() < deadline:
            actual_given = max(0, last_like - baseline)
            if target is not None and actual_given >= target:
                break

            if target is None:
                # Full mode is intentionally bounded so a serverless function cannot hang.
                batch_size = min(10, len(tokens) - token_index)
            else:
                remaining_target = max(1, target - actual_given)
                batch_size = min(remaining_target, 20, len(tokens) - token_index)

            batch = tokens[token_index:token_index + batch_size]
            token_index += batch_size
            attempted += len(batch)

            ok_count, fail_count, results = await send_like_batch(
                session, encrypted_uid, batch, like_url, deadline
            )
            success_requests += ok_count
            failed += fail_count

            for i, result in enumerate(results, start=1):
                if not result[0]:
                    app.logger.warning(f"JWT #{attempted - len(batch) + i} failed: {result[2]}")

            # One profile check per batch, not one profile request per JWT.
            if time.monotonic() >= deadline:
                break

            profile = await asyncio.to_thread(sync_profile_request, encrypted_uid, server_name, profile_token)
            checks += 1
            if profile is not None:
                try:
                    last_like = profile_to_dict(profile)["likes"]
                    actual_given = max(0, last_like - baseline)
                    app.logger.info(
                        f"Batch complete: JWTs={len(batch)}, actual_likes={actual_given}, target={target}"
                    )
                    if target is not None and actual_given >= target:
                        break
                except Exception as exc:
                    app.logger.warning(f"Profile parse failed after batch: {exc}")
            else:
                # If profile lookup fails, continue with the next batch only while time remains.
                app.logger.warning("Profile check failed after like batch; continuing with bounded retry.")

    actual_given = max(0, last_like - baseline)
    return {
        "attempted": attempted,
        "success_requests": success_requests,
        "failed": failed,
        "actual_likes": actual_given,
        "target": target,
        "target_reached": target is None or actual_given >= target,
        "profile_checks": checks,
        "elapsed_seconds": round(time.monotonic() - start, 2),
        "token_pool": len(tokens),
    }


@app.get("/")
def health():
    return jsonify({
        "status": "ok",
        "service": "Free Fire Like API",
        "usage": "/like?uid=<UID>&server_name=<REGION>&likes=<TARGET>",
    })


@app.get("/health")
def health2():
    return jsonify({"status": "ok"})


@app.get("/like")
def handle_requests():
    uid = str(request.args.get("uid", "")).strip()
    server_name = str(request.args.get("server_name", "")).strip().upper()

    if not uid or not uid.isdigit():
        return jsonify({"error": "UID must be numeric"}), 400
    if not server_name:
        return jsonify({"error": "server_name is required"}), 400

    likes_param = request.args.get("likes") or request.args.get("target")
    full_mode = str(request.args.get("full", "0")).lower() in {"1", "true", "yes", "full"}
    likes_limit = None
    if not full_mode and likes_param not in (None, ""):
        try:
            likes_limit = int(likes_param)
            if likes_limit < 1:
                return jsonify({"error": "likes/target must be >= 1"}), 400
        except ValueError:
            return jsonify({"error": "likes/target must be an integer"}), 400

    tokens = load_tokens(server_name)
    if not tokens:
        return jsonify({"error": f"No valid tokens found for region {server_name}"}), 500

    encrypted_profile_uid = enc_profile(uid)
    if encrypted_profile_uid is None:
        return jsonify({"error": "Encryption of UID failed"}), 500

    # Initial profile: try a few tokens only. Never spend the entire request timeout here.
    before = None
    working_token = None
    for token in tokens[:3]:
        before = sync_profile_request(encrypted_profile_uid, server_name, token)
        if before is not None:
            working_token = token
            break

    if before is None:
        return jsonify({
            "error": "Unable to read player profile with the first available JWTs",
            "hint": "Check token files and region token validity.",
        }), 502

    try:
        before_data = profile_to_dict(before)
        before_like = before_data["likes"]
    except Exception as exc:
        return jsonify({"error": f"Profile decode failed: {exc}"}), 502

    like_url = REGION_LIKE_URLS.get(server_name, DEFAULT_LIKE_URL)

    try:
        result = asyncio.run(
            send_multiple_requests(
                uid=uid,
                server_name=server_name,
                url=like_url,
                likes_limit=likes_limit,
                before_like=before_like,
                working_token=working_token,
            )
        )
    except Exception as exc:
        app.logger.exception("Like processing crashed")
        return jsonify({"error": f"Like processing failed: {exc}"}), 500

    if not isinstance(result, dict):
        return jsonify({"error": "Like processing returned no result"}), 502
    if result.get("error"):
        return jsonify(result), 500

    # Final profile check is best-effort and bounded. If it fails, use the last verified
    # value from the batch loop instead of turning a successful request into a 500.
    after = None
    for token in [working_token] + [t for t in tokens[:5] if t != working_token]:
        if not token:
            continue
        after = sync_profile_request(encrypted_profile_uid, server_name, token)
        if after is not None:
            break

    player_uid = int(uid)
    player_name = before_data.get("nickname", "")
    player_region = before_data.get("region", "") or server_name
    player_level = before_data.get("level", "")
    after_like = before_like + int(result.get("actual_likes", 0))

    if after is not None:
        try:
            after_data = profile_to_dict(after)
            after_like = after_data["likes"]
            player_uid = after_data["uid"] or player_uid
            player_name = after_data["nickname"] or player_name
            player_region = after_data["region"] or player_region
            player_level = after_data["level"] or player_level
        except Exception as exc:
            app.logger.warning(f"Final profile parse failed: {exc}")

    like_given = max(0, after_like - before_like)
    # When the final profile is unavailable, preserve the verified batch result.
    if after is None:
        like_given = max(0, int(result.get("actual_likes", 0)))
        after_like = before_like + like_given

    target_reached = (
        full_mode or likes_limit is None and result.get("target") is None
        or (likes_limit is not None and like_given >= likes_limit)
    )

    return jsonify({
        "LikesGivenByAPI": like_given,
        "LikesbeforeCommand": before_like,
        "LikesafterCommand": after_like,
        "TargetLikes": None if full_mode else likes_limit,
        "TargetReached": bool(target_reached),
        "AttemptedJWTs": int(result.get("attempted", 0)),
        "SuccessfulJWTRequests": int(result.get("success_requests", 0)),
        "FailedJWTs": int(result.get("failed", 0)),
        "ProfileChecks": int(result.get("profile_checks", 0)),
        "ElapsedSeconds": result.get("elapsed_seconds", 0),
        "TokenPool": int(result.get("token_pool", len(tokens))),
        "PlayerNickname": player_name,
        "PlayerRegion": player_region,
        "PlayerLevel": player_level,
        "UID": player_uid,
        "status": 1 if like_given > 0 else 2,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False, use_reloader=False)
