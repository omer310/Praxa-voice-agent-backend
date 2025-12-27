from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from livekit import api
import os

app = FastAPI()

# CORS - allow your Expo app to call this
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your app domains
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
        # Create access token
        token = api.AccessToken(
            os.environ["LIVEKIT_API_KEY"],
            os.environ["LIVEKIT_API_SECRET"],
        )
        
        # Set participant identity
        token.with_identity(request.participantName)
        
        # Add room join permissions
        token.with_grants(api.VideoGrants(
            room_join=True,
            room=request.roomName,
        ))
        
        # Add user metadata (agent will receive this)
        if request.userId or request.nylasGrantId:
            token.with_metadata(
                f'{{"userId": "{request.userId or ""}", "nylasGrantId": "{request.nylasGrantId or ""}"}}'
            )
        
        return {
            "token": token.to_jwt(),
            "url": os.environ["LIVEKIT_URL"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def health():
    return {"status": "ok"}
