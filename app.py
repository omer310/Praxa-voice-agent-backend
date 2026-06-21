from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from livekit import api
import os
import httpx
from typing import List, Optional

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY") or os.environ.get("ELEVEN_LABS_API_KEY", "")

_VOICE_META: dict[str, dict] = {
    "EXAVITQu4vr4xnSDxMaL": {"name": "Sarah", "persona": "Clear & Professional"},
    "r5iFzIytiA1rzjhWFCjW": {"name": "Adam",  "persona": "Deep & Confident"},
    "21m00Tcm4TlvDq8ikWAM": {"name": "Rachel", "persona": "Warm & Calm"},
    "AZnzlk1XvdvUeBnXmlld": {"name": "Domi",   "persona": "Bright & Direct"},
    "D38z5RcWu1voky8WS1ja": {"name": "Fin",    "persona": "Friendly & Measured"},
}
_voices_cache: list | None = None

app = FastAPI()

# Native mobile clients don't send Origin headers, so CORS only guards
# browser-based callers. Restrict to known origins; set ALLOWED_ORIGINS
# (comma-separated) in the Railway environment to add production domains.
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins or ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


async def _verify_supabase_jwt(request: Request) -> str:
    """Verify a Supabase JWT and return the authenticated user_id.

    Raises HTTPException 401 if the token is missing or invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header.split(" ", 1)[1].strip()
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(status_code=500, detail="Supabase not configured on token server")

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": SUPABASE_ANON_KEY,
                },
            )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Unauthorized")
        data = resp.json()
        user_id = data.get("id") or data.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return user_id
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Token Server] JWT verification error: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized")


class TokenRequest(BaseModel):
    roomName: str
    participantName: str
    userId: Optional[str] = None
    emailGrantId: Optional[str] = None
    calendarGrantId: Optional[str] = None
    timezone: Optional[str] = None
    initiativeNames: Optional[List[str]] = None
    sessionId: Optional[str] = None
    voiceId: Optional[str] = None

@app.post("/token")
async def create_token(request: TokenRequest, authenticated_user_id: str = Depends(_verify_supabase_jwt)):
    try:
        if request.userId and request.userId != authenticated_user_id:
            raise HTTPException(status_code=403, detail="userId in request does not match authenticated user")

        effective_user_id = request.userId or authenticated_user_id

        livekit_url = os.environ.get("LIVEKIT_URL")
        livekit_api_key = os.environ.get("LIVEKIT_API_KEY")
        livekit_api_secret = os.environ.get("LIVEKIT_API_SECRET")
        
        if not all([livekit_url, livekit_api_key, livekit_api_secret]):
            raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
        
        token = api.AccessToken(livekit_api_key, livekit_api_secret)
        token.with_identity(request.participantName)
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=request.roomName,
        ))
        
        email_grant = request.emailGrantId or ""
        calendar_grant = request.calendarGrantId or ""

        import json as _json
        metadata_dict = {
            "user_id": effective_user_id,
            "email_grant_id": email_grant,
            "calendar_grant_id": calendar_grant,
            "timezone": request.timezone or "UTC",
        }
        if request.initiativeNames:
            metadata_dict["initiative_names"] = request.initiativeNames
        if request.sessionId:
            metadata_dict["session_id"] = request.sessionId
        if request.voiceId:
            metadata_dict["voice_id"] = request.voiceId
        metadata_json = _json.dumps(metadata_dict)

        token.with_metadata(metadata_json)

        token.with_room_config(
            api.RoomConfiguration(
                agents=[
                    api.RoomAgentDispatch(
                        agent_name="voice-assistant",
                        metadata=metadata_json,
                    )
                ],
            )
        )

        print(f"[Token Server] Dispatching agent for user_id: {effective_user_id}, email_grant: {email_grant[:20] if email_grant else 'none'}, calendar_grant: {calendar_grant[:20] if calendar_grant else 'none'}")
        
        return {
            "token": token.to_jwt(),
            "url": livekit_url
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Token Server] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/voices")
async def get_voices():
    """Return curated voice list with ElevenLabs preview URLs (cached after first fetch)."""
    global _voices_cache
    if _voices_cache is not None:
        return _voices_cache

    preview_by_id: dict[str, str] = {}
    if not ELEVENLABS_API_KEY:
        print("[/voices] ELEVENLABS_API_KEY not set — previews unavailable")
    else:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # One bulk call is cheaper and more reliable than per-voice lookups.
            try:
                resp = await client.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": ELEVENLABS_API_KEY},
                )
                if resp.status_code == 200:
                    for v in resp.json().get("voices", []):
                        vid = v.get("voice_id")
                        if vid and v.get("preview_url"):
                            preview_by_id[vid] = v["preview_url"]
                else:
                    print(f"[/voices] bulk list returned {resp.status_code}")
            except Exception as e:
                print(f"[/voices] bulk fetch failed: {e}")

            # Fill any gaps (e.g. premade voices not in the account's list) individually.
            for voice_id in _VOICE_META:
                if voice_id in preview_by_id:
                    continue
                try:
                    r = await client.get(
                        f"https://api.elevenlabs.io/v1/voices/{voice_id}",
                        headers={"xi-api-key": ELEVENLABS_API_KEY},
                    )
                    if r.status_code == 200:
                        url = r.json().get("preview_url")
                        if url:
                            preview_by_id[voice_id] = url
                except Exception as e:
                    print(f"[/voices] preview fetch failed for {voice_id}: {e}")

    voices = [
        {"id": voice_id, **meta, "previewUrl": preview_by_id.get(voice_id)}
        for voice_id, meta in _VOICE_META.items()
    ]

    # Only cache once we actually have previews, so a missing key or transient
    # error at boot doesn't permanently poison the response.
    if preview_by_id:
        _voices_cache = voices
    return voices


@app.get("/")
async def health():
    return {"status": "ok", "service": "praxa-livekit-token-server"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}