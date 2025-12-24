# Quick Start Guide

## 🎯 Initial Setup

### Step 1: Verify Installation
All dependencies have been installed. Verify with:
```bash
npm ls
```

### Step 2: Configure Environment Variables

Create a `.env` file in the root directory with your API keys:

```bash
# Deepgram Configuration
DEEPGRAM_API_KEY=your_deepgram_api_key_here

# OpenAI Configuration  
OPENAI_API_KEY=your_openai_api_key_here

# JWT Configuration
JWT_SECRET=generate_a_random_secret_key_here
JWT_EXPIRY=24h

# Server Configuration
PORT=3000
NODE_ENV=development
LOG_LEVEL=debug

# CORS Configuration (comma-separated URLs)
CORS_ORIGINS=http://localhost:8081,http://localhost:3000
```

**How to get API keys:**
- **Deepgram**: Visit https://console.deepgram.com and create API key
- **OpenAI**: Visit https://platform.openai.com and create API key
- **JWT_SECRET**: Generate a random string (e.g., using `openssl rand -hex 32`)

### Step 3: Start the Server

**Development mode** (with auto-reload):
```bash
npm run dev
```

**Production mode**:
```bash
npm start
```

You should see:
```
{"timestamp":"2025-12-24T12:00:00.000Z","level":"INFO","message":"Server listening on port 3000","env":"development","corsOrigins":["http://localhost:8081","http://localhost:3000"]}
```

### Step 4: Test the Server

#### Health Check
```bash
curl http://localhost:3000/health
```

Expected response:
```json
{
  "status": "ok",
  "timestamp": "2025-12-24T12:00:00.000Z",
  "activeSessions": 0
}
```

#### Generate JWT Token
```bash
curl -X POST http://localhost:3000/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"userId":"test_user_123"}'
```

Expected response:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "sessionId": "session_1702800000000_abc123def",
  "expiresIn": "24h",
  "type": "Bearer"
}
```

#### Verify Token
```bash
curl http://localhost:3000/api/auth/verify \
  -H "Authorization: Bearer <token_from_above>"
```

#### Start a Session
```bash
curl -X POST http://localhost:3000/api/session/start \
  -H "Content-Type: application/json" \
  -d '{"userId":"test_user_123"}'
```

## 🔌 Testing WebSocket Connection

### Using Socket.io Client (JavaScript)

```javascript
const io = require('socket.io-client');

// 1. Get token from REST API
const tokenResponse = await fetch('http://localhost:3000/api/session/start', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ userId: 'test_user_123' })
});
const { token } = await tokenResponse.json();

// 2. Connect socket
const socket = io('http://localhost:3000', {
  auth: { token }
});

// 3. Set up listeners
socket.on('authenticated', (data) => {
  console.log('Connected:', data);
  socket.emit('get_session_status');
});

socket.on('session_status', (data) => {
  console.log('Session status:', data);
});

socket.on('error', (error) => {
  console.error('Error:', error);
});

socket.on('disconnect', () => {
  console.log('Disconnected');
});
```

## 📁 Project Structure Overview

```
praxis-voice-agent-backend/
├── config/                 # Configuration management
│   └── config.js          # Loads and validates env vars
├── controllers/           # Business logic
│   └── voiceController.js # Manages voice sessions
├── middleware/            # Express/Socket.io middleware
│   └── authMiddleware.js  # JWT verification
├── services/              # External service integrations
│   └── deepgramService.js # Deepgram WebSocket client
├── routes/                # REST API endpoints
│   ├── authRoutes.js      # /api/auth/* endpoints
│   └── voiceRoutes.js     # /api/session/* endpoints
├── utils/                 # Utility functions
│   ├── authUtils.js       # JWT token utilities
│   ├── logger.js          # Logging system
│   └── socketHandlers.js  # Socket.io event handlers
├── server.js              # Entry point & server setup
├── package.json           # Dependencies
├── .env                   # Environment variables (create this)
├── .gitignore            # Git ignore rules
└── README.md             # Full documentation
```

## 🔑 Key Files Explained

### `server.js`
- Express app setup
- Socket.io initialization
- Route registration
- Graceful shutdown handling

### `config/config.js`
- Environment variable loading
- Configuration validation
- Default values

### `services/deepgramService.js`
- WebSocket connection to Deepgram
- Audio forwarding
- Message handling

### `controllers/voiceController.js`
- Session lifecycle management
- Deepgram connection management
- Audio routing

### `utils/socketHandlers.js`
- Socket.io event listeners
- Client-to-server communication
- Real-time event handling

## 🐛 Debugging

### Enable Debug Logging
```bash
LOG_LEVEL=debug npm run dev
```

### Check Active Sessions
```bash
curl http://localhost:3000/api/session/active-count
```

### Monitor Server Logs
```bash
tail -f logs/server.log  # If you add file logging
```

## 🚀 Next Steps

1. **Integrate with Expo app** - Use Socket.io client in your React Native app
2. **Add audio processing** - Record microphone input and send to backend
3. **Add error handling** - Implement retry logic and error recovery
4. **Performance monitoring** - Add metrics and health checks
5. **Database integration** - Connect to Supabase for user data if needed

## ⚙️ Configuration Examples

### For Production
```env
NODE_ENV=production
LOG_LEVEL=warn
PORT=8080
JWT_EXPIRY=7d
CORS_ORIGINS=https://app.example.com,https://www.example.com
```

### For Testing
```env
NODE_ENV=test
LOG_LEVEL=debug
PORT=3001
DEEPGRAM_API_KEY=test_key
OPENAI_API_KEY=test_key
JWT_SECRET=test_secret
```

## 📞 Support

- **Deepgram Docs**: https://developers.deepgram.com/
- **OpenAI Docs**: https://platform.openai.com/docs
- **Socket.io Docs**: https://socket.io/docs/
- **Express Docs**: https://expressjs.com/

## ✅ Checklist

- [ ] `.env` file created with all required keys
- [ ] Server starts without errors (`npm run dev`)
- [ ] Health check endpoint responds
- [ ] JWT token generation works
- [ ] Can verify JWT tokens
- [ ] Can start voice sessions via REST API
- [ ] Can connect via Socket.io with token
- [ ] Active session count reflects connections

Once all items are checked, your backend is ready for integration with the Expo app!

