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
        logger.debug('Initialize voice request', { socketId: socket.id, sessionId });

        // Initialize Deepgram connection
        await voiceController.initializeDeepgramConnection(sessionId);

        // Register event handlers for this socket
        voiceController.registerEventHandlers(sessionId, {
          onSettingsApplied: (data) => {
            socket.emit('settings_applied', data);
          },
          onTranscript: (data) => {
            socket.emit('transcript', data);
          },
          onAgentAudio: (audioBuffer) => {
            // Send binary audio data
            socket.emit('audio_response', audioBuffer);
          },
          onError: (error) => {
            socket.emit('error', {
              message: error.message,
              code: 'DEEPGRAM_ERROR'
            });
          },
          onClose: () => {
            socket.emit('voice_ended');
          }
        });

        socket.emit('voice_initialized', {
          message: 'Voice session initialized',
          sessionId
        });

        logger.info('Voice session initialized', { socketId: socket.id, sessionId });
      } catch (error) {
        logger.error('Failed to initialize voice', {
          socketId: socket.id,
          sessionId,
          error: error.message
        });
        socket.emit('error', {
          message: error.message,
          code: 'INITIALIZATION_ERROR'
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

