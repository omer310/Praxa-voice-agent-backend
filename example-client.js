/**
 * Example Socket.io Client Test
 * 
 * This file demonstrates how to connect to the voice agent backend
 * and interact with the real-time voice API.
 * 
 * Usage:
 *   1. Start the server: npm run dev
 *   2. Install socket.io-client: npm install socket.io-client
 *   3. Run this file: node example-client.js
 */

const io = require('socket.io-client');

// Configuration
const SERVER_URL = 'http://localhost:3000';
const TEST_USER_ID = 'test_user_' + Date.now();

console.log('🚀 Praxis Voice Agent Backend - Client Example\n');
console.log(`📡 Connecting to: ${SERVER_URL}`);
console.log(`👤 User ID: ${TEST_USER_ID}\n`);

// Step 1: Get authentication token
async function getAuthToken() {
  try {
    console.log('📝 Step 1: Requesting authentication token...');
    const response = await fetch(`${SERVER_URL}/api/session/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userId: TEST_USER_ID })
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    console.log(`✅ Token received`);
    console.log(`   Session ID: ${data.sessionId}`);
    console.log(`   Token (first 50 chars): ${data.token.substring(0, 50)}...\n`);

    return data.token;
  } catch (error) {
    console.error('❌ Failed to get token:', error.message);
    process.exit(1);
  }
}

// Step 2: Connect via Socket.io
function connectSocket(token) {
  return new Promise((resolve, reject) => {
    console.log('🔌 Step 2: Connecting via Socket.io...');

    const socket = io(SERVER_URL, {
      auth: { token },
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      reconnectionAttempts: 5
    });

    socket.on('connect', () => {
      console.log(`✅ Connected to server`);
      console.log(`   Socket ID: ${socket.id}\n`);
      resolve(socket);
    });

    socket.on('connect_error', (error) => {
      console.error('❌ Connection error:', error.message);
      reject(error);
    });

    socket.on('error', (error) => {
      console.error('❌ Socket error:', error);
    });

    socket.on('disconnect', (reason) => {
      console.log(`\n⚠️  Disconnected: ${reason}`);
    });
  });
}

// Step 3: Set up event listeners
function setupEventListeners(socket) {
  console.log('📨 Step 3: Setting up event listeners...\n');

  socket.on('authenticated', (data) => {
    console.log('✅ Socket authenticated');
    console.log(`   Message: ${data.message}`);
    console.log(`   Session ID: ${data.sessionId}\n`);
  });

  socket.on('voice_initialized', (data) => {
    console.log('🎤 Voice session initialized');
    console.log(`   ${data.message}\n`);
  });

  socket.on('session_status', (data) => {
    console.log('📊 Session Status:');
    console.log(`   Status: ${data.status}`);
    console.log(`   Connected to Deepgram: ${data.isConnectedToDeepgram}`);
    console.log(`   Started at: ${data.startedAt}`);
    console.log(`   Transcripts received: ${data.transcriptCount}\n`);
  });

  socket.on('transcript', (data) => {
    console.log(`📝 Transcript (final: ${data.isFinal}): ${data.transcript}`);
  });

  socket.on('audio_response', (audioBuffer) => {
    console.log(`🔊 Received audio response (${audioBuffer.byteLength} bytes)`);
  });

  socket.on('session_ended', (data) => {
    console.log(`\n✅ ${data.message}`);
    console.log(`   Session ID: ${data.sessionId}\n`);
  });

  socket.on('error', (error) => {
    console.error(`\n❌ Error: ${error.message}`);
    if (error.code) {
      console.error(`   Code: ${error.code}`);
    }
  });
}

// Step 4: Simulate voice interaction
async function simulateVoiceInteraction(socket) {
  console.log('🎯 Step 4: Simulating voice interaction...\n');

  return new Promise((resolve) => {
    // Initialize voice after a short delay
    setTimeout(() => {
      console.log('Initializing voice session...');
      socket.emit('initialize_voice');
    }, 1000);

    // Get session status after initialization
    setTimeout(() => {
      console.log('Requesting session status...');
      socket.emit('get_session_status');
    }, 2000);

    // Simulate ending after 5 seconds
    setTimeout(() => {
      console.log('\nEnding session...');
      socket.emit('end_session');
    }, 5000);

    // Complete after 6 seconds
    setTimeout(() => {
      resolve();
    }, 6000);
  });
}

// Main execution
async function main() {
  try {
    // Get authentication token
    const token = await getAuthToken();

    // Connect via Socket.io
    const socket = await connectSocket(token);

    // Set up event listeners
    setupEventListeners(socket);

    // Simulate voice interaction
    await simulateVoiceInteraction(socket);

    // Cleanup
    socket.disconnect();
    console.log('🏁 Example completed successfully!\n');
    process.exit(0);
  } catch (error) {
    console.error('💥 Error:', error.message);
    process.exit(1);
  }
}

// Run the example
main();

