const voiceController = require('../controllers/voiceController');
const logger = require('../utils/logger');

/**
 * Initialize Socket.io event handlers for voice interactions
 * @param {Server} io - Socket.io server instance
 */
function initializeSocketHandlers(io) {
  // Register connection handler for new clients
  io.on('connection', (socket) => {
    const userId = socket.user.userId;
    const sessionId = socket.sessionId;

    logger.info('Socket.io client connected', {
      socketId: socket.id,
      userId,
      sessionId
    });

    // Create session in activeSessions if it doesn't exist
    // This ensures session exists for all subsequent handlers
    let session = voiceController.getSession(sessionId);
    if (!session) {
      // Create a new session for this Socket.io connection
      const sessionData = {
        userId,
        sessionId,
        startedAt: new Date(),
        status: 'initialized',
        transcripts: [],
        isConnectedToDeepgram: false,
        settingsApplied: false  // Track if Deepgram Settings have been confirmed
      };
      voiceController.activeSessions.set(sessionId, sessionData);
      logger.debug('Session created for Socket.io connection', { sessionId, userId });
    }

    // Send authentication confirmation
    socket.emit('authenticated', {
      message: 'Successfully authenticated',
      socketId: socket.id,
      sessionId,
      userId
    });

    // ==========================================
    // Voice Interaction Event Handlers
    // ==========================================

    /**
     * 'initialize_voice' event
     * Client sends this to initialize the Deepgram connection
     */
    socket.on('initialize_voice', async () => {
      try {
        logger.info('🎙️ Initialize voice request received', { 
          socketId: socket.id, 
          sessionId,
          userId 
        });

        // Register event handlers for this socket BEFORE connecting
        // This ensures they're in place when Deepgram's events fire
        voiceController.registerEventHandlers(sessionId, {
          onOpen: () => {
            // WebSocket is open, but Settings haven't been confirmed yet
            // DO NOT emit voice_initialized here - wait for SettingsApplied!
            logger.info('✅ Deepgram WebSocket OPEN - waiting for SettingsApplied...', { sessionId });
          },
          onSettingsApplied: (data) => {
            // NOW it's safe to emit voice_initialized!
            // Deepgram has confirmed Settings, so updatePrompt will work
            logger.info('⚙️ Settings applied from Deepgram - NOW emitting voice_initialized', { sessionId });
            
            // Mark settings as applied so updatePrompt is allowed
            const sessionData = voiceController.getSession(sessionId);
            if (sessionData) {
              sessionData.settingsApplied = true;
            }
            
            socket.emit('settings_applied', data);
            
            // Emit voice_initialized AFTER SettingsApplied
            socket.emit('voice_initialized', {
              message: 'Voice session initialized and ready',
              sessionId
            });
            logger.info('✅ Voice session fully initialized and ready (after SettingsApplied)', { 
              socketId: socket.id, 
              sessionId 
            });
          },
          onTranscript: (data) => {
            logger.info('📝 Transcript received', { 
              sessionId, 
              type: data.type,
              transcript: data.transcript 
            });
            socket.emit('transcript', data);
          },
          onAgentAudio: (audioBuffer) => {
            logger.info('🔊 Agent audio received', { 
              sessionId, 
              size: audioBuffer.length 
            });
            // Send binary audio data
            socket.emit('audio_response', audioBuffer);
          },
          onError: (error) => {
            console.error('🚨 === SOCKET ERROR HANDLER START ===');
            console.error('Session ID:', sessionId);
            console.error('Error Object:', JSON.stringify(error, null, 2));
            console.error('Error Message:', error.message);
            console.error('Error Code:', error.code);
            console.error('Error Type:', error.type);
            console.error('Error Stack:', error.stack);
            console.error('🚨 === SOCKET ERROR HANDLER END ===');
            
            logger.error('❌ Deepgram error in session', { 
              sessionId, 
              error: error.message,
              stack: error.stack 
            });
            socket.emit('error', {
              message: error.message,
              code: 'DEEPGRAM_ERROR'
            });
          },
          onClose: () => {
            logger.info('🔌 Deepgram connection closed', { sessionId });
            socket.emit('voice_ended');
          }
        });

        // Initialize Deepgram connection AFTER registering handlers
        // This ensures onOpen handler is in place when Deepgram's Open event fires
        logger.info('🔗 Attempting to connect to Deepgram Voice Agent...', { sessionId });
        await voiceController.initializeDeepgramConnection(sessionId);
        logger.info('✅ Deepgram connection established successfully', { sessionId });
        
        // voice_initialized will be emitted by the onOpen handler above
        // after WebSocket connection is fully established
      } catch (error) {
        logger.error('❌ CRITICAL: Failed to initialize voice session', {
          socketId: socket.id,
          sessionId,
          userId,
          errorMessage: error.message,
          errorStack: error.stack,
          errorName: error.name
        });
        socket.emit('error', {
          message: error.message,
          code: 'INITIALIZATION_ERROR',
          details: error.stack
        });
      }
    });

    /**
     * 'audio_data' event
     * Client sends binary audio data
     */
    socket.on('audio_data', (audioBuffer) => {
      try {
        if (!Buffer.isBuffer(audioBuffer)) {
          logger.warn('Invalid audio data format', { socketId: socket.id });
          return;
        }

        logger.debug('Received audio data', {
          socketId: socket.id,
          sessionId,
          size: audioBuffer.length
        });

        // Forward audio to Deepgram
        voiceController.forwardAudioToDeepgram(sessionId, audioBuffer);
      } catch (error) {
        logger.error('Error processing audio data', {
          socketId: socket.id,
          sessionId,
          error: error.message
        });
        socket.emit('error', {
          message: 'Failed to process audio data',
          code: 'AUDIO_PROCESSING_ERROR'
        });
      }
    });

    /**
     * 'end_session' event
     * Client sends this to end the voice session
     */
    socket.on('end_session', () => {
      try {
        logger.info('End session request', { socketId: socket.id, sessionId });

        voiceController.endSession(sessionId);

        socket.emit('session_ended', {
          message: 'Session ended successfully',
          sessionId
        });

        logger.info('Session ended', { socketId: socket.id, sessionId });
      } catch (error) {
        logger.error('Failed to end session', {
          socketId: socket.id,
          sessionId,
          error: error.message
        });
        socket.emit('error', {
          message: 'Failed to end session',
          code: 'SESSION_END_ERROR'
        });
      }
    });

    /**
     * 'get_session_status' event
     * Client requests the current session status
     */
    socket.on('get_session_status', () => {
      try {
        const session = voiceController.getSession(sessionId);

        if (!session) {
          socket.emit('error', {
            message: 'Session not found',
            code: 'SESSION_NOT_FOUND'
          });
          return;
        }

        socket.emit('session_status', {
          sessionId,
          status: session.status,
          isConnectedToDeepgram: session.isConnectedToDeepgram,
          startedAt: session.startedAt,
          transcriptCount: session.transcripts.length
        });

        logger.debug('Session status sent', { socketId: socket.id, sessionId });
      } catch (error) {
        logger.error('Failed to get session status', {
          socketId: socket.id,
          sessionId,
          error: error.message
        });
        socket.emit('error', {
          message: 'Failed to get session status',
          code: 'STATUS_ERROR'
        });
      }
    });

    /**
     * 'interrupt' event
     * Client sends this to interrupt/stop the agent mid-response
     * Allows user to speak over agent or pause conversation
     * 
     * Deepgram Voice Agent supports barge-in (user interrupting agent)
     * This handler enables real-time, natural conversation
     */
    socket.on('interrupt', () => {
      try {
        logger.info('Interrupt request received', { socketId: socket.id, sessionId });

        // Stop the agent (Deepgram will stop TTS output)
        voiceController.interruptAgent(sessionId);

        socket.emit('agent_interrupted', {
          message: 'Agent stopped - ready for new input',
          sessionId
        });

        logger.debug('Agent interrupted successfully', { socketId: socket.id, sessionId });
      } catch (error) {
        logger.error('Failed to interrupt agent', {
          socketId: socket.id,
          sessionId,
          error: error.message
        });
        socket.emit('error', {
          message: 'Failed to interrupt agent',
          code: 'INTERRUPT_ERROR'
        });
      }
    });

    /**
     * 'update_system_prompt' event
     * Client sends this to inject user context into the LLM
     * Allows personalizing the agent with user data (tasks, calendar, preferences)
     * 
     * This is critical for:
     * - Personalizing responses with user context
     * - Injecting tasks/calendar/integrations data
     * - Customizing agent behavior based on user preferences
     * - Real-time context updates during conversation
     */
    socket.on('update_system_prompt', (data) => {
      try {
        const { prompt } = data;

        if (!prompt || typeof prompt !== 'string') {
          logger.warn('Invalid prompt data', { 
            socketId: socket.id, 
            sessionId,
            promptType: typeof prompt
          });
          socket.emit('error', {
            message: 'Invalid prompt format. Expected string.',
            code: 'INVALID_PROMPT_FORMAT'
          });
          return;
        }

        // Check if Deepgram Settings have been applied
        // CRITICAL: updatePrompt MUST NOT be called before Settings are confirmed!
        const sessionData = voiceController.getSession(sessionId);
        if (!sessionData?.settingsApplied) {
          logger.warn('⚠️ update_system_prompt called BEFORE SettingsApplied! Rejecting.', { 
            socketId: socket.id, 
            sessionId,
            settingsApplied: sessionData?.settingsApplied,
            isConnectedToDeepgram: sessionData?.isConnectedToDeepgram
          });
          socket.emit('error', {
            message: 'Voice session not ready. Please wait for voice_initialized event before updating prompt.',
            code: 'SETTINGS_NOT_APPLIED'
          });
          return;
        }

        logger.info('Update system prompt request', { 
          socketId: socket.id, 
          sessionId,
          promptLength: prompt.length
        });

        // Update Deepgram LLM system prompt (instructions)
        voiceController.updateSystemPrompt(sessionId, prompt);

        socket.emit('prompt_updated', {
          message: 'System prompt updated successfully',
          sessionId,
          promptLength: prompt.length
        });

        logger.debug('System prompt updated', { 
          socketId: socket.id, 
          sessionId,
          promptLength: prompt.length
        });
      } catch (error) {
        logger.error('Failed to update system prompt', {
          socketId: socket.id,
          sessionId,
          error: error.message
        });
        socket.emit('error', {
          message: 'Failed to update system prompt',
          code: 'PROMPT_UPDATE_ERROR'
        });
      }
    });

    // ==========================================
    // Disconnection Handlers
    // ==========================================

    socket.on('disconnect', (reason) => {
      logger.info('Socket.io client disconnected', {
        socketId: socket.id,
        sessionId,
        reason
      });

      // End the voice session on disconnect
      voiceController.endSession(sessionId);
    });

    socket.on('error', (error) => {
      logger.error('Socket.io error', {
        socketId: socket.id,
        sessionId,
        error: error.message || error
      });
    });
  });
}

module.exports = {
  initializeSocketHandlers
};

