const WebSocket = require('ws');
const config = require('../config/config');
const logger = require('../utils/logger');

class DeepgramService {
  constructor() {
    this.connections = new Map(); // Map of sessionId -> deepgramWebSocket
    this.eventHandlers = new Map(); // Map of sessionId -> client event handlers
  }

  /**
   * Connect to Deepgram Voice Agent API
   * @param {string} sessionId - User session ID
   * @param {Object} eventHandlers - Event handlers for audio events
   * @param {Function} eventHandlers.onTranscript - Handle transcription updates
   * @param {Function} eventHandlers.onAgentResponse - Handle agent text response
   * @param {Function} eventHandlers.onAudioResponse - Handle audio response
   * @param {Function} eventHandlers.onError - Handle errors
   * @param {Function} eventHandlers.onClose - Handle connection close
   * @returns {Promise<void>}
   */
  async connect(sessionId, eventHandlers) {
    return new Promise((resolve, reject) => {
      try {
        logger.info('Connecting to Deepgram Voice Agent', { sessionId });

        const wsUrl = config.deepgramEndpoint;
        const ws = new WebSocket(wsUrl, ['token', config.deepgramApiKey]);

        ws.binaryType = 'arraybuffer';

        ws.onopen = () => {
          logger.info('Connected to Deepgram Voice Agent', { sessionId });
          
          // Send settings configuration
          const settings = {
            type: 'SettingsConfiguration',
            audio: {
              encoding: 'linear16',
              sample_rate: 16000
            },
            agent: {
              listen: {
                model: config.deepgramModel
              },
              think: {
                provider: {
                  type: 'openai',
                  model: 'gpt-4'
                }
              },
              speak: {
                model: config.deepgramVoiceModel
              }
            }
          };

          ws.send(JSON.stringify(settings));
          logger.debug('Sent SettingsConfiguration to Deepgram', { sessionId });

          this.connections.set(sessionId, ws);
          this.eventHandlers.set(sessionId, eventHandlers);
          
          resolve();
        };

        ws.onmessage = (event) => {
          this._handleDeegramMessage(sessionId, event);
        };

        ws.onerror = (error) => {
          logger.error('Deepgram WebSocket error', { sessionId, error: error.message });
          eventHandlers.onError?.(error);
          reject(error);
        };

        ws.onclose = () => {
          logger.info('Disconnected from Deepgram Voice Agent', { sessionId });
          this.connections.delete(sessionId);
          this.eventHandlers.delete(sessionId);
          eventHandlers.onClose?.();
        };

      } catch (error) {
        logger.error('Failed to connect to Deepgram', { sessionId, error: error.message });
        reject(error);
      }
    });
  }

  /**
   * Send audio to Deepgram
   * @param {string} sessionId - User session ID
   * @param {ArrayBuffer} audioBuffer - Audio data
   */
  sendAudio(sessionId, audioBuffer) {
    const ws = this.connections.get(sessionId);
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      logger.warn('Cannot send audio: no active connection', { sessionId });
      return;
    }

    try {
      ws.send(audioBuffer);
    } catch (error) {
      logger.error('Failed to send audio to Deepgram', { sessionId, error: error.message });
    }
  }

  /**
   * Handle messages from Deepgram
   * @private
   */
  _handleDeegramMessage(sessionId, event) {
    try {
      const handlers = this.eventHandlers.get(sessionId);
      if (!handlers) {
        logger.warn('No handlers found for session', { sessionId });
        return;
      }

      // Check if message is binary (audio)
      if (event.data instanceof ArrayBuffer) {
        logger.debug('Received audio response from Deepgram', { sessionId, size: event.data.byteLength });
        handlers.onAudioResponse?.(event.data);
        return;
      }

      // Parse text message
      let message;
      if (typeof event.data === 'string') {
        message = JSON.parse(event.data);
      } else {
        // Convert blob to string if needed
        const reader = new FileReader();
        reader.onload = () => {
          message = JSON.parse(reader.result);
          this._processDeepgramMessage(sessionId, message, handlers);
        };
        reader.readAsText(event.data);
        return;
      }

      this._processDeepgramMessage(sessionId, message, handlers);
    } catch (error) {
      logger.error('Failed to process Deepgram message', { sessionId, error: error.message });
    }
  }

  /**
   * Process parsed Deepgram message
   * @private
   */
  _processDeepgramMessage(sessionId, message, handlers) {
    logger.debug('Processing Deepgram message', { sessionId, type: message.type });

    switch (message.type) {
      case 'UserStartedSpeaking':
        logger.debug('User started speaking', { sessionId });
        break;

      case 'Transcript':
        logger.debug('Received transcript', { sessionId, transcript: message.transcript });
        handlers.onTranscript?.({
          transcript: message.transcript,
          isFinal: message.is_final || false
        });
        break;

      case 'AgentThinking':
        logger.debug('Agent is thinking', { sessionId });
        break;

      case 'AgentSpeaking':
        logger.debug('Agent is speaking', { sessionId });
        break;

      case 'UserStoppedSpeaking':
        logger.debug('User stopped speaking', { sessionId });
        break;

      case 'Error':
        logger.error('Deepgram error', { sessionId, error: message.message });
        handlers.onError?.(new Error(message.message));
        break;

      default:
        logger.debug('Unknown Deepgram message type', { sessionId, type: message.type });
    }
  }

  /**
   * Disconnect from Deepgram
   * @param {string} sessionId - User session ID
   */
  disconnect(sessionId) {
    const ws = this.connections.get(sessionId);
    if (ws) {
      logger.info('Closing Deepgram connection', { sessionId });
      ws.close();
      this.connections.delete(sessionId);
      this.eventHandlers.delete(sessionId);
    }
  }

  /**
   * Check if a session is connected
   * @param {string} sessionId - User session ID
   * @returns {boolean}
   */
  isConnected(sessionId) {
    const ws = this.connections.get(sessionId);
    return ws && ws.readyState === WebSocket.OPEN;
  }

  /**
   * Disconnect all active connections (for graceful shutdown)
   */
  disconnectAll() {
    logger.info('Disconnecting all Deepgram sessions');
    for (const [sessionId, ws] of this.connections.entries()) {
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    }
    this.connections.clear();
    this.eventHandlers.clear();
  }
}

module.exports = new DeepgramService();

