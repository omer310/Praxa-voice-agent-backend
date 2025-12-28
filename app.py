from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from livekit import api
import os

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
    userId: str = None
    nylasGrantId: str = None

@app.post("/token")
async def create_token(request: TokenRequest):
    try:
        # Get LiveKit credentials from environment
        livekit_url = os.environ.get("LIVEKIT_URL")
        livekit_api_key = os.environ.get("LIVEKIT_API_KEY")
        livekit_api_secret = os.environ.get("LIVEKIT_API_SECRET")
        
        if not all([livekit_url, livekit_api_key, livekit_api_secret]):
            raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
        
        # Create access token
        token = api.AccessToken(livekit_api_key, livekit_api_secret)
        
        token.with_identity(request.participantName)
        
        # Add room join permissions
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=request.roomName,
        ))
        
        # Add user metadata and dispatch voice-assistant agent
        if request.userId or request.nylasGrantId:
            # Add metadata to participant
            token.with_metadata(
                f'{{"userId": "{request.userId or ""}", "nylasGrantId": "{request.nylasGrantId or ""}"}}'
            )
            
            # Dispatch the voice-assistant agent with metadata
            token.with_room_config(
                api.RoomConfiguration(
                    agents=[
                        api.RoomAgentDispatch(
                            agent_name="voice-assistant",
                            metadata=f'{{"userId": "{request.userId or ""}", "nylasGrantId": "{request.nylasGrantId or ""}"}}'
                        )
                    ],
                )
            )
        
        return {
            "token": token.to_jwt(),
            "url": livekit_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def health():
    return {"status": "ok", "service": "praxa-livekit-token-server"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}