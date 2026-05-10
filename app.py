import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional, List

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx
from supabase import create_client, Client

from tools import UserData, TOOL_LABELS, dispatch_tool
from system_prompt import build_instructions
from session_config import TOOLS

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


@dataclass
class SessionData:
    user_data: UserData
    created_at: float = field(default_factory=time.time)


active_sessions: dict[str, SessionData] = {}


def _get_supabase() -> Client | None:
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            return create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as e:
            logger.error(f"Failed to create Supabase client: {e}")
    return None


class SessionRequest(BaseModel):
    userId: str
    emailGrantId: Optional[str] = None
    calendarGrantId: Optional[str] = None
    timezone: Optional[str] = "UTC"
    initiativeNames: Optional[List[str]] = None
    voicePreference: Optional[str] = None


ALLOWED_VOICE_PREVIEW_IDS = frozenset({
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
})


class VoicePreviewBody(BaseModel):
    voice: str


@app.post("/session")
async def create_session(req: SessionRequest):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    sb = _get_supabase()

    user_id = req.userId
    email_grant_id = req.emailGrantId
    calendar_grant_id = req.calendarGrantId
    timezone = req.timezone or "UTC"
    initiative_names = req.initiativeNames or []
    voice = req.voicePreference or "coral"

    if sb and user_id:
        try:
            ai_check = await asyncio.to_thread(
                lambda: sb.table("users").select("ai_enabled").eq("id", user_id).maybe_single().execute()
            )
            row = ai_check.data if ai_check else None
            if isinstance(row, dict) and not row.get("ai_enabled", True):
                raise HTTPException(status_code=403, detail="Voice assistant is disabled for this account.")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Could not check ai_enabled for user {user_id}: {e}")

        try:
            email_task = asyncio.to_thread(
                lambda: sb.table("nylas_oauth_tokens").select("grant_id").eq(
                    "user_id", user_id
                ).eq("integration_type", "email").maybe_single().execute()
            )
            calendar_task = asyncio.to_thread(
                lambda: sb.table("nylas_oauth_tokens").select("grant_id").eq(
                    "user_id", user_id
                ).eq("integration_type", "calendar").maybe_single().execute()
            )
            voice_task = asyncio.to_thread(
                lambda: sb.table("user_settings").select("voice_preference").eq(
                    "user_id", user_id
                ).maybe_single().execute()
            )

            email_result, calendar_result, voice_result = await asyncio.gather(
                email_task, calendar_task, voice_task, return_exceptions=True
            )

            if not isinstance(email_result, Exception):
                _data = getattr(email_result, "data", None)
                if _data:
                    email_grant_id = _data.get("grant_id") or email_grant_id

            if not isinstance(calendar_result, Exception):
                _data = getattr(calendar_result, "data", None)
                if _data:
                    calendar_grant_id = _data.get("grant_id") or calendar_grant_id

            if not isinstance(voice_result, Exception):
                _data = getattr(voice_result, "data", None)
                if _data:
                    voice = _data.get("voice_preference") or voice

        except Exception as e:
            logger.error(f"Error fetching user data from Supabase: {e}")

    if email_grant_id:
        email_grant_id = str(email_grant_id)
    if calendar_grant_id:
        calendar_grant_id = str(calendar_grant_id)

    logger.info(
        f"Creating session for user={user_id}, voice={voice}, "
        f"email_grant={'set' if email_grant_id else 'missing'}, "
        f"calendar_grant={'set' if calendar_grant_id else 'missing'}"
    )

    instructions = build_instructions(timezone, initiative_names)

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "session": {
                    "type": "realtime",
                    "model": "gpt-realtime-2",
                    "instructions": instructions,
                    "tools": TOOLS,
                    "tool_choice": "auto",
                    "output_modalities": ["audio"],
                    "parallel_tool_calls": True,
                    "reasoning": {"effort": "low"},
                    "audio": {
                        "input": {
                            "transcription": {"model": "gpt-4o-mini-transcribe"},
                            "turn_detection": {"type": "semantic_vad"},
                        },
                        "output": {
                            "voice": voice,
                        },
                    },
                },
                "expires_after": {"anchor": "created_at", "seconds": 60},
            },
        )

        if response.status_code != 200:
            logger.error(f"OpenAI session creation failed: {response.status_code} {response.text[:300]}")
            raise HTTPException(status_code=502, detail=f"OpenAI session creation failed: {response.status_code}")

        ga_response = response.json()
        ephemeral_token = ga_response.get("value")
        session_obj = ga_response.get("session", {})
        session_id = session_obj.get("id")

        if not session_id or not ephemeral_token:
            raise HTTPException(status_code=502, detail="OpenAI returned no session ID or token")

    ud = UserData(
        user_id=user_id,
        email_grant_id=email_grant_id,
        calendar_grant_id=calendar_grant_id,
        supabase=sb,
        timezone=timezone,
    )
    active_sessions[session_id] = SessionData(user_data=ud)

    _cleanup_stale_sessions()

    logger.info(f"Session created: {session_id} (gpt-realtime-2)")
    return {
        "id": session_id,
        "client_secret": {"value": ephemeral_token},
        "model": "gpt-realtime-2",
    }


@app.post("/voice/preview")
async def voice_preview(body: VoicePreviewBody):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    vid = body.voice.strip().lower()
    if vid not in ALLOWED_VOICE_PREVIEW_IDS:
        raise HTTPException(status_code=400, detail="Invalid voice")

    snippet = (
        "Hi — I'm Praxa. This is a quick sample "
        "so you can hear how I'll sound when we talk by voice."
    )

    last_err = ""
    audio_bytes = b""
    async with httpx.AsyncClient(timeout=60.0) as client:
        for model in ("gpt-4o-mini-tts", "tts-1"):
            r = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "voice": vid,
                    "input": snippet,
                },
            )
            if r.status_code == 200:
                audio_bytes = r.content
                break
            last_err = f"{model}: {r.status_code} {r.text[:160]}"

    if not audio_bytes:
        logger.warning("Voice preview TTS failed: %s", last_err)
        raise HTTPException(status_code=502, detail="Could not generate preview")

    b64 = base64.b64encode(audio_bytes).decode("ascii")
    return JSONResponse({"format": "mp3", "audio_base64": b64})


@app.websocket("/ws/{session_id}")
async def sideband(ws: WebSocket, session_id: str):
    await ws.accept()

    session = active_sessions.get(session_id)
    if not session:
        logger.warning(f"WebSocket connected for unknown session_id={session_id}")
        await ws.close(code=4404)
        return

    ud = session.user_data
    logger.info(f"Sideband WebSocket connected for session={session_id}, user={ud.user_id}")

    try:
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") != "tool_call":
                continue

            name = msg.get("name", "")
            call_id = msg.get("call_id", "")
            raw_args = msg.get("arguments", "{}")

            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
            else:
                args = raw_args

            logger.info(f"Tool call: {name} (call_id={call_id})")

            label = TOOL_LABELS.get(name, "Thinking...")
            try:
                await ws.send_text(json.dumps({"type": "praxa_thinking", "label": label}))
            except Exception:
                pass

            result = await dispatch_tool(name, args, ud)
            logger.info(f"Tool {name} result (first 100 chars): {str(result)[:100]}")

            await ws.send_text(json.dumps({
                "type": "tool_result",
                "call_id": call_id,
                "output": result,
            }))

            try:
                await ws.send_text(json.dumps({"type": "praxa_thinking", "label": ""}))
            except Exception:
                pass

    except WebSocketDisconnect:
        logger.info(f"App disconnected from sideband session={session_id}")
    except Exception as e:
        logger.error(f"Sideband error for session={session_id}: {e}", exc_info=True)
    finally:
        active_sessions.pop(session_id, None)
        logger.info(f"Sideband cleaned up for session={session_id}")


@app.post("/call/incoming")
async def call_incoming(request: dict):
    """Stub for Twilio SIP / OpenAI phone call webhook (Phase 3)."""
    logger.info(f"Incoming call event: {json.dumps(request)[:200]}")
    return {"status": "ok"}


@app.get("/")
async def health():
    return {"status": "ok", "service": "praxa-realtime-backend"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


def _cleanup_stale_sessions(max_age_seconds: int = 3600):
    now = time.time()
    stale = [sid for sid, s in active_sessions.items() if now - s.created_at > max_age_seconds]
    for sid in stale:
        active_sessions.pop(sid, None)
        logger.info(f"Cleaned up stale session: {sid}")
