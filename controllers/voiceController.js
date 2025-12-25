const deepgramService = require('../services/deepgramService');
const authUtils = require('../utils/authUtils');
const logger = require('../utils/logger');

class VoiceController {
  constructor() {
    this.activeSessions = new Map(); // Map of sessionId -> session data
  }

  /**
   * Start a new voice session
   * @param {string} userId - User ID
   * @returns {Promise<Object>} Session info with JWT token
   */
  async startSession(userId) {
    try {
      const sessionPayload = authUtils.createSessionPayload(userId);
      const token = authUtils.generateToken(sessionPayload);

      const sessionData = {
        userId,
        sessionId: sessionPayload.sessionId,
        startedAt: new Date(),
        token,
        status: 'initialized',
        transcripts: [],
        isConnectedToDeepgram: false
      };

      this.activeSessions.set(sessionPayload.sessionId, sessionData);

      logger.info('Voice session started', {
        userId,
        sessionId: sessionPayload.sessionId
      });

      return {
        sessionId: sessionPayload.sessionId,
        userId,
        token,
        message: 'Session initialized. Use this token to connect via WebSocket.'
      };
    } catch (error) {
      logger.error('Failed to start session', { userId, error: error.message });
      throw error;
    }
  }

  /**
   * Initialize Deepgram connection for a session
   * @param {string} sessionId - Session ID
   * @returns {Promise<void>}
   */
  async initializeDeepgramConnection(sessionId) {
    try {
      const sessionData = this.activeSessions.get(sessionId);
      if (!sessionData) {
        throw new Error(`Session not found: ${sessionId}`);
      }

      if (sessionData.isConnectedToDeepgram) {
        logger.warn('Deepgram already connected for session', { sessionId });
        return;
      }

      const eventHandlers = {
        onOpen: () => {
          sessionData.isConnectedToDeepgram = true;
          logger.debug('Deepgram connection opened', { sessionId });
          if (sessionData.onOpen) {
            sessionData.onOpen();
          }
        },
        onSettingsApplied: (data) => {
          logger.debug('Settings applied', { sessionId });
          if (sessionData.onSettingsApplied) {
            sessionData.onSettingsApplied(data);
          }
        },
        onTranscript: (data) => {
          sessionData.transcripts.push({
            timestamp: new Date(),
            ...data
          });
          // Emit to socket.io via the socket handler
          if (sessionData.onTranscript) {
            sessionData.onTranscript(data);
          }
        },
        onAgentAudio: (audioBuffer) => {
          // Emit audio to socket.io via the socket handler
          if (sessionData.onAgentAudio) {
            sessionData.onAgentAudio(audioBuffer);
          }
        },
        onError: (error) => {
          logger.error('Deepgram error in session', { sessionId, error: error.message });
          if (sessionData.onError) {
            sessionData.onError(error);
          }
        },
        onClose: () => {
          sessionData.isConnectedToDeepgram = false;
          if (sessionData.onClose) {
            sessionData.onClose();
          }
        }
      };

      await deepgramService.connect(sessionId, eventHandlers);
      sessionData.isConnectedToDeepgram = true;
      sessionData.status = 'connected';

      logger.info('Deepgram connection established', { sessionId });
    } catch (error) {
      logger.error('Failed to initialize Deepgram connection', { sessionId, error: error.message });
      throw error;
    }
  }

  /**
   * Handle audio from client and forward to Deepgram
   * @param {string} sessionId - Session ID
   * @param {ArrayBuffer} audioBuffer - Audio data
   */
  forwardAudioToDeepgram(sessionId, audioBuffer) {
    try {
      if (!deepgramService.isConnected(sessionId)) {
        logger.warn('Cannot forward audio: Deepgram not connected', { sessionId });
        return;
      }

      deepgramService.sendAudio(sessionId, audioBuffer);
    } catch (error) {
      logger.error('Failed to forward audio to Deepgram', { sessionId, error: error.message });
    }
  }

  /**
   * Register event handlers for a session (used by socket.io)
   * @param {string} sessionId - Session ID
   * @param {Object} handlers - Event handlers
   */
  registerEventHandlers(sessionId, handlers) {
    const sessionData = this.activeSessions.get(sessionId);
    if (sessionData) {
      sessionData.onOpen = handlers.onOpen;
      sessionData.onSettingsApplied = handlers.onSettingsApplied;
      sessionData.onTranscript = handlers.onTranscript;
      sessionData.onAgentAudio = handlers.onAgentAudio;
      sessionData.onError = handlers.onError;
      sessionData.onClose = handlers.onClose;
    }
  }

  /**
   * End a voice session
   * @param {string} sessionId - Session ID
   */
  endSession(sessionId) {
    try {
      const sessionData = this.activeSessions.get(sessionId);
      if (!sessionData) {
        logger.warn('Session not found when ending', { sessionId });
        return;
      }

      deepgramService.disconnect(sessionId);
      this.activeSessions.delete(sessionId);

      logger.info('Voice session ended', {
        sessionId,
        userId: sessionData.userId,
        duration: new Date() - sessionData.startedAt
      });
    } catch (error) {
      logger.error('Failed to end session', { sessionId, error: error.message });
    }
  }

  /**
   * Interrupt the agent mid-response
   * Deepgram Voice Agent supports barge-in (user interrupting agent output)
   * This method stops the current agent response, allowing user to speak
   * 
   * @param {string} sessionId - Session ID
   */
  interruptAgent(sessionId) {
    try {
      const sessionData = this.activeSessions.get(sessionId);
      if (!sessionData) {
        logger.warn('Session not found when interrupting', { sessionId });
        return;
      }

      if (!sessionData.isConnectedToDeepgram) {
        logger.warn('Cannot interrupt: Deepgram not connected', { sessionId });
        return;
      }

      // Use the existing injectUserMessage to handle interruption
      // This naturally resets the agent's state and makes it ready to listen
      deepgramService.injectUserMessage(sessionId, '');

      logger.info('Agent interrupted', { sessionId });
    } catch (error) {
      logger.error('Failed to interrupt agent', { sessionId, error: error.message });
    }
  }

  /**
   * Update the system prompt with user context
   * Allows injecting user-specific data (tasks, calendar, preferences)
   * into the LLM instructions for personalized responses
   * 
   * Use cases:
   * - Personalize agent with user information
   * - Inject tasks/calendar/email data
   * - Customize agent behavior based on user preferences
   * - Real-time context updates during conversation
   * 
   * @param {string} sessionId - Session ID
   * @param {string} newPrompt - New system prompt with user context
   */
  updateSystemPrompt(sessionId, newPrompt) {
    try {
      const sessionData = this.activeSessions.get(sessionId);
      if (!sessionData) {
        logger.warn('Session not found when updating prompt', { sessionId });
        return;
      }

      if (!sessionData.isConnectedToDeepgram) {
        logger.warn('Cannot update prompt: Deepgram not connected', { sessionId });
        return;
      }

      if (!newPrompt || typeof newPrompt !== 'string') {
        logger.warn('Invalid prompt provided', { 
          sessionId, 
          promptType: typeof newPrompt 
        });
        return;
      }

      // Update Deepgram LLM system prompt (instructions)
      deepgramService.updatePrompt(sessionId, newPrompt);

      // Store in session for reference
      sessionData.currentPrompt = newPrompt;

      logger.info('System prompt updated with user context', { 
        sessionId, 
        promptLength: newPrompt.length 
      });
    } catch (error) {
      logger.error('Failed to update system prompt', { sessionId, error: error.message });
    }
  }

  /**
   * Get session data (for debugging/monitoring)
   * @param {string} sessionId - Session ID
   * @returns {Object|null} Session data or null if not found
   */
  getSession(sessionId) {
    return this.activeSessions.get(sessionId) || null;
  }

  /**
   * Get all active sessions count
   * @returns {number}
   */
  getActiveSessionCount() {
    return this.activeSessions.size;
  }

  /**
   * Graceful shutdown - close all sessions
   */
  gracefulShutdown() {
    logger.info('Shutting down voice controller', {
      activeSessions: this.activeSessions.size
    });

    for (const [sessionId, sessionData] of this.activeSessions.entries()) {
      this.endSession(sessionId);
    }
  }
}

module.exports = new VoiceController();

