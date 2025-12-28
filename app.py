from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from livekit import api
import os
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST"],
    allow_headers=["*"],
)

class TokenRequest(BaseModel):
    roomName: str
    participantName: str
    userId: Optional[str] = None
    emailGrantId: Optional[str] = None
    calendarGrantId: Optional[str] = None

@app.post("/token")
async def create_token(request: TokenRequest):
    try:
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
        
        if request.userId:
            email_grant = request.emailGrantId or ""
            calendar_grant = request.calendarGrantId or ""
            
            metadata_json = f'{{"userId": "{request.userId}", "emailGrantId": "{email_grant}", "calendarGrantId": "{calendar_grant}"}}'
            
            token.with_metadata(metadata_json)
            
            token.with_room_config(
                api.RoomConfiguration(
                    agents=[
                        api.RoomAgentDispatch(
                            agent_name="voice-assistant",
                            metadata=metadata_json
                        )
                    ],
                )
            )
            
            print(f"[Token Server] Dispatching agent for userId: {request.userId}, emailGrant: {email_grant[:20] if email_grant else 'none'}, calendarGrant: {calendar_grant[:20] if calendar_grant else 'none'}")
        else:
            print("[Token Server] Warning: No userId provided")
        
        return {
            "token": token.to_jwt(),
            "url": livekit_url
        }
    except Exception as e:
        print(f"[Token Server] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def health():
    return {"status": "ok", "service": "praxa-livekit-token-server"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}