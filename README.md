# Praxa Voice Agent Backend

A real-time voice agent backend service that facilitates communication between the Expo app and Deepgram's Voice Agent API, integrated with OpenAI for conversational responses.

## 🏗️ Architecture

The backend uses a modern Node.js stack with the following key components:

- **Express.js** - HTTP API and request handling
- **Socket.io** - Real-time WebSocket communication for audio streaming
- **Deepgram Voice Agent API** - Unified STT (speech-to-text), LLM, and TTS (text-to-speech)
- **OpenAI** - Conversational intelligence via GPT-4
- **JWT** - Secure authentication and session management

### Data Flow

```
Expo App → Socket.io → Backend → Deepgram Voice Agent
         ↓                           ↓
       Audio                   ↓ Deepgram
       Streams              [STT → OpenAI → TTS]
         ↑                           ↓
       Audio ← Backend ← Deepgram ← Audio Response
```

## 📋 Project Structure

```
/praxis-voice-agent-backend
├── /config              # Configuration and environment management
│   └── config.js        # Environment variables loader
├── /controllers         # Business logic for voice interactions
│   └── voiceController.js
├── /middleware          # Express/Socket.io middleware
│   └── authMiddleware.js
├── /services            # External service integrations
│   └── deepgramService.js
├── /routes              # API endpoint definitions
│   ├── authRoutes.js
│   └── voiceRoutes.js
├── /utils               # Utility functions
│   ├── authUtils.js     # JWT token utilities
│   ├── logger.js        # Logging utility
│   └── socketHandlers.js # Socket.io event handlers
├── server.js            # Entry point
└── package.json
```

## 🚀 Getting Started

### Prerequisites

- Node.js 16+ 
- npm or yarn
- Deepgram API key (from https://console.deepgram.com)
- OpenAI API key (from https://platform.openai.com)

### Installation

1. **Install dependencies** (already done):
   ```bash
   npm install
   npm install --save-dev nodemon
   ```

2. **Set up environment variables**:
   Create a `.env` file in the root directory:
   ```bash
   # Deepgram Configuration
   DEEPGRAM_API_KEY=your_deepgram_api_key_here

   # OpenAI Configuration
   OPENAI_API_KEY=your_openai_api_key_here

   # JWT Configuration
   JWT_SECRET=your_jwt_secret_key_here
   JWT_EXPIRY=24h

   # Server Configuration
   PORT=3000
   NODE_ENV=development
   LOG_LEVEL=debug

   # CORS Configuration (comma-separated)
   CORS_ORIGINS=http://localhost:8081,http://localhost:3000
   ```

3. **Start the server**:
   ```bash
   # Development mode (with auto-reload)
   npm run dev

   # Production mode
   npm start
   ```

The server will start on `http://localhost:3000`

## 📡 API Endpoints

### Authentication

#### `POST /api/auth/token`
Generate a JWT token for user authentication.

**Request:**
```json
{
  "userId": "user_123"
}
```

**Response:**
```json
{
  "token": "eyJhbGc...",
  "sessionId": "session_1234567890_abc123def",
  "expiresIn": "24h",
  "type": "Bearer"
}
```

#### `GET /api/auth/verify`
Verify JWT token validity.

**Headers:**
```
Authorization: Bearer <token>
```

**Response:**
```json
{
  "valid": true,
  "payload": {
    "userId": "user_123",
    "sessionId": "session_1234567890_abc123def",
    "createdAt": "2025-12-24T12:00:00Z",
    "type": "voice_session"
  }
}
```

### Voice Sessions

#### `POST /api/session/start`
Start a new voice session.

**Request:**
```json
{
  "userId": "user_123"
}
```

**Response:**
```json
{
  "sessionId": "session_1234567890_abc123def",
  "userId": "user_123",
  "token": "eyJhbGc...",
  "message": "Session initialized. Use this token to connect via WebSocket."
}
```

#### `GET /api/session/status`
Get the status of an active session.

**Headers:**
```
Authorization: Bearer <token>
```

**Response:**
```json
{
  "sessionId": "session_1234567890_abc123def",
  "status": "connected",
  "isConnectedToDeepgram": true,
  "startedAt": "2025-12-24T12:00:00Z",
  "transcriptCount": 5
}
```

#### `POST /api/session/end`
End an active voice session.

**Headers:**
```
Authorization: Bearer <token>
```

**Response:**
```json
{
  "message": "Session ended successfully",
  "sessionId": "session_1234567890_abc123def"
}
```

#### `GET /api/session/active-count`
Get the count of active sessions (for monitoring).

**Response:**
```json
{
  "activeSessionCount": 3
}
```

### Health Check

#### `GET /health`
Check server health status.

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2025-12-24T12:00:00Z",
  "activeSessions": 2
}
```

## 🔌 WebSocket Events

The backend communicates with clients via Socket.io using the following events:

### Client → Server Events

#### `initialize_voice`
Initialize the voice interaction with Deepgram.

```javascript
socket.emit('initialize_voice');
```

#### `audio_data`
Send audio chunks to the backend.

```javascript
socket.emit('audio_data', audioBuffer);
```

#### `end_session`
End the current voice session.

```javascript
socket.emit('end_session');
```

#### `get_session_status`
Request the current session status.

```javascript
socket.emit('get_session_status');
```

### Server → Client Events

#### `authenticated`
Sent after successful authentication.

```json
{
  "message": "Successfully authenticated",
  "socketId": "socket_id_xyz",
  "sessionId": "session_123",
  "userId": "user_123"
}
```

#### `voice_initialized`
Voice session has been initialized with Deepgram.

```json
{
  "message": "Voice session initialized",
  "sessionId": "session_123"
}
```

#### `transcript`
Real-time transcription updates.

```json
{
  "transcript": "Hello, how are you?",
  "isFinal": false
}
```

#### `audio_response`
Audio chunks from Deepgram's text-to-speech.

```
Binary audio data (ArrayBuffer)
```

#### `session_status`
Response to `get_session_status`.

```json
{
  "sessionId": "session_123",
  "status": "connected",
  "isConnectedToDeepgram": true,
  "startedAt": "2025-12-24T12:00:00Z",
  "transcriptCount": 5
}
```

#### `session_ended`
Session has ended.

```json
{
  "message": "Session ended successfully",
  "sessionId": "session_123"
}
```

#### `error`
Error occurred during processing.

```json
{
  "message": "Error description",
  "code": "ERROR_CODE"
}
```

## 📚 Usage Example (Expo Client)

```javascript
import io from 'socket.io-client';

// 1. Get token from backend
const response = await fetch('http://localhost:3000/api/session/start', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ userId: 'user_123' })
});
const { token, sessionId } = await response.json();

// 2. Connect via Socket.io
const socket = io('http://localhost:3000', {
  auth: { token }
});

// 3. Initialize voice
socket.emit('initialize_voice');

// 4. Listen for events
socket.on('transcript', (data) => {
  console.log('User said:', data.transcript);
});

socket.on('audio_response', (audioBuffer) => {
  // Play audio using Expo Audio API
  playAudio(audioBuffer);
});

socket.on('error', (error) => {
  console.error('Error:', error.message);
});

// 5. Send audio
const audioChunk = await recordAudio();
socket.emit('audio_data', audioChunk);

// 6. End session
socket.emit('end_session');
```

## 🔐 Authentication Flow

1. **Client requests token**: POST `/api/auth/token` with userId
2. **Backend generates JWT**: Token includes userId, sessionId, and session type
3. **Client connects to Socket.io**: Passes token in handshake auth
4. **Backend verifies JWT**: Middleware checks token validity
5. **Connection established**: Client can now stream audio

## 📊 Monitoring

### Active Sessions
Monitor active sessions via the health endpoint:
```bash
curl http://localhost:3000/api/session/active-count
```

### Logs
The server logs all important events:
- Connection/disconnection events
- JWT token generation/verification
- Deepgram connection status
- Audio streaming activity
- Errors and warnings

Log format:
```json
{
  "timestamp": "2025-12-24T12:00:00.000Z",
  "level": "INFO",
  "message": "description",
  "metadata": "additional context"
}
```

## 🛠️ Development

### Running in Development Mode
```bash
npm run dev
```

This uses `nodemon` to automatically restart the server on file changes.

### Environment Debugging
Enable debug logging:
```bash
export LOG_LEVEL=debug
npm run dev
```

## 📝 Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 3000 | Server port |
| `NODE_ENV` | development | Environment mode |
| `LOG_LEVEL` | info | Logging level (debug, info, warn, error) |
| `JWT_EXPIRY` | 24h | JWT token expiration time |
| `DEEPGRAM_MODEL` | nova-2 | Deepgram speech recognition model |
| `DEEPGRAM_VOICE_MODEL` | aura-asteria-en | Deepgram TTS voice model |
| `CORS_ORIGINS` | localhost:8081,localhost:3000 | Allowed CORS origins |

## 🐛 Troubleshooting

### Connection Issues
- Verify Deepgram API key is correct
- Check CORS origins match your client URL
- Ensure JWT_SECRET is set

### Audio Not Processing
- Check audio format is 16-bit linear PCM at 16kHz
- Verify Deepgram service is connected
- Review server logs for errors

### Authentication Errors
- Ensure token is passed in Socket.io auth
- Check token hasn't expired
- Verify JWT_SECRET matches across requests

## 📖 Documentation References

- [Deepgram Voice Agent API](https://developers.deepgram.com/)
- [OpenAI API](https://platform.openai.com/docs)
- [Socket.io Documentation](https://socket.io/docs/)
- [Express.js](https://expressjs.com/)

## 🔄 Deployment

### Production Checklist

1. Set `NODE_ENV=production`
2. Use strong `JWT_SECRET`
3. Configure `CORS_ORIGINS` for production domain
4. Use environment-specific `.env` file
5. Enable rate limiting
6. Set up monitoring and error tracking
7. Use HTTPS for WebSocket connections (wss://)

### Deployment Example (Heroku)

```bash
heroku config:set DEEPGRAM_API_KEY=<key>
heroku config:set OPENAI_API_KEY=<key>
heroku config:set JWT_SECRET=<secret>
heroku config:set NODE_ENV=production
git push heroku main
```

## 📄 License

MIT

## 👥 Support

For issues or questions:
1. Check the troubleshooting section
2. Review server logs
3. Consult Deepgram and OpenAI documentation

