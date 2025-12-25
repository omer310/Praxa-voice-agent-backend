const { createClient, AgentEvents } = require('@deepgram/sdk');
const config = require('../config/config');
const logger = require('../utils/logger');

/**
 * Deepgram Voice Agent Service
 * 
 * LAST UPDATED: December 24, 2025
 * SDK VERSION: v4.7.0 (June 25, 2025)
 * 
 * ⚠️ KNOWN ISSUES FROM GITHUB (December 2025):
 * 
 * Issue #443 - Voice Agent TTS audio renders as static (CRITICAL)
 *   Status: OPEN - No workaround available
 *   Impact: TTS responses may have audio quality issues
 *   Tracking: Monitor for Deepgram fix
 * 
 * Issue #426 - Live ASR fails on Node.js < 22 (CRITICAL)
 *   Status: OPEN - Requires Node.js 22+
 *   Implementation: package.json engines set to Node.js >=22
 * 
 * Issue #400 - AgentThinking not returned (OPEN)
 *   Status: May miss thinking events
 *   Implementation: Handler added for when it becomes available
 * 
 * Issue #346 - isBrowser initialization error (OPEN)
 *   Status: Low impact (backend-only, not browser)
 *   Implementation: Using config layer avoids direct env access
 * 
 * Issue #326 - Invalid base URL wss://api.deepgram.com (OPEN)
 *   Status: URL validation could fail
 *   Implementation: Monitor for SDK fix
 * 
 * Issue #294 - Custom URL last segment removed (OPEN)
 *   Status: May affect EU endpoint path
 *   Implementation: EU endpoint configured as api.eu.deepgram.com
 * 
 * Issue #366 - AbstractLiveClient send() is ASYNC (STILL OPEN ⚠️)
 *   Status: send() returns Promise without proper await support
 *   Impact: High-frequency audio streaming requires non-blocking
 *   Implementation: Using .catch() handler for error handling
 * 
 * Issue #354 - Message Format Errors (STILL OPEN ⚠️)
 *   Status: Message format must match exactly
 *   Impact: Injection validation required
 *   Implementation: Strict validation + error capture
 * 
 * Issue #349 - Direct process.env Access (STILL OPEN ⚠️)
 *   Status: SDK issues with direct env access
 *   Impact: Use config abstraction
 *   Implementation: All env via config.js
 * 
 * Issue #386 - Punctuate Feature (STILL BROKEN ⚠️)
 *   Status: Punctuation not working
 *   Impact: Avoid punctuate setting
 * 
 * Issue #392 - Backend Token Auth (STILL OPEN ⚠️)
 *   Status: Unclear guidance for backend tokens
 *   Impact: Use API key directly
 * 
 * Issue #372 - Expo TTS Support (STILL OPEN ⚠️)
 *   Status: Known Expo limitation
 *   Impact: Test with real devices
 * 
 * Issues #329, #326 - React Native WebSocket (STILL OPEN ⚠️)
 *   Status: Buffer handling issues
 *   Impact: Validate buffers strictly
 * 
 * Issue #395 - Browser Compatibility (STILL OPEN ⚠️)
 *   Status: Browser issues (not relevant for backend)
 * 
 * DECEMBER 2025 NEW FEATURES:
 * 
 * EU Endpoint Support (GA: Dec 3, 2025)
 *   - Available: api.eu.deepgram.com
 *   - All APIs supported (STT, TTS, Voice Agent, Text Intelligence)
 *   - Use for GDPR/European compliance
 *   - Config: Set DEEPGRAM_ENDPOINT environment variable
 * 
 * Aura-2 Extended Language Support (GA: Dec 11, 2025)
 *   - NEW: Dutch, German, French, Italian, Japanese
 *   - Previously: English only
 *   - Model: aura-2-[language]-[variant]
 *   - Examples: aura-2-en-neural, aura-2-fr-neural, aura-2-de-neural
 * 
 * SDK v4.7.0 Improvements (June 25, 2025):
 *   - Prerecorded transcription simplified
 *   - Callback vs synchronous methods separated
 *   - Isomorphic design (browser + Node.js)
 *   - Function-based initialization
 *   - Scoped constructor configuration
 *   - Enhanced error messaging ✅
 *   - On-premises deployment support
 *   - Future product readiness
 * 
 * EXPO COMPATIBILITY NOTES:
 * - Audio format must be linear16 PCM at 16kHz
 * - Use Expo.Audio API for recording
 * - Handle zero-byte audio buffers gracefully
 * - Monitor connection keep-alive intervals
 * - Test with real devices (simulator has audio limitations)
 * - See Issue #372 for known Expo TTS limitations
 * 
 * BACKEND ARCHITECTURE SUMMARY:
 * - This service creates ONE Deepgram connection per user session
 * - Keep-alive intervals maintained per connection
 * - Proper cleanup on disconnect (prevents memory leaks)
 * - Fire-and-forget audio streaming for low-latency
 * - Error handling for all SDK operations
 * - Comprehensive logging for production monitoring
 * - Compatible with EU endpoint for GDPR compliance
 * - Supports new Aura-2 multilingual voices
 */

class DeepgramService {
  constructor() {
    // Voice Agent connections
    this.agentConnections = new Map(); // Map of sessionId -> agent connection
    this.eventHandlers = new Map(); // Map of sessionId -> client event handlers
    
    // Initialize Deepgram client
    this.deepgramClient = createClient(config.deepgramApiKey);
  }

  /**
   * Connect to Deepgram Voice Agent API
   * Voice Agent handles: STT + LLM + TTS all in one
   * 
   * @param {string} sessionId - User session ID
   * @param {Object} eventHandlers - Event handlers for voice events
   * @param {Function} eventHandlers.onTranscript - Handle transcription updates
   * @param {Function} eventHandlers.onAgentAudio - Handle agent audio response
   * @param {Function} eventHandlers.onSettingsApplied - Handle settings applied confirmation
   * @param {Function} eventHandlers.onError - Handle errors
   * @param {Function} eventHandlers.onClose - Handle connection close
   * @returns {Promise<void>}
   */
  async connect(sessionId, eventHandlers) {
    return new Promise((resolve, reject) => {
      try {
        logger.info('Connecting to Deepgram Voice Agent API', { sessionId });

        // Configure Voice Agent with your LLM of choice
        // Note: Input and output audio default to linear16 at 16000 Hz but are configurable
        const agentConfig = {
          model: 'default', // Uses Flux for STT by default
          language: 'en-US',
          listen: {
            model: config.deepgramListenModel || 'nova-3'
          },
          think: {
            provider: {
              type: config.deepgramLLMProvider || 'open_ai', // 'open_ai', 'anthropic', 'google', 'groq'
              model: config.deepgramLLMModel || 'gpt-4o-mini'
            },
            instructions: config.deepgramSystemPrompt || 'You are a helpful voice assistant. Keep responses concise and natural for voice conversation.'
          },
          speak: {
            model: config.deepgramVoiceModel || 'aura-asteria-en'
          },
          // Optional greeting message to start the conversation
          greeting: config.deepgramGreeting || 'Hello! How can I help you today?',
          // Flux end-of-turn timeout (default 5000ms, max 10000ms)
          // This is the maximum silence allowed before a turn is forcefully ended
          eot_timeout_ms: config.deepgramEotTimeout || 5000
          
          // Optional: Agent context for maintaining conversation state
          // Documented in: /docs/configure-voice-agent#agentcontext
          // Can be configured via environment if needed
        };

        // Connect to Voice Agent API
        // Updated method name: deepgram.agent() not deepgram.agent.converse()
        const connection = this.deepgramClient.agent(agentConfig);

        // Store handlers
        this.eventHandlers.set(sessionId, eventHandlers);
        this.agentConnections.set(sessionId, connection);

        // Handle Open event
        connection.on(AgentEvents.Open, () => {
          logger.info('Connected to Deepgram Voice Agent API', { sessionId });
          
          // Set up keep-alive every 5 seconds
          const keepAliveInterval = setInterval(() => {
            try {
              connection.keepAlive();
              logger.debug('Keep-alive sent', { sessionId });
            } catch (error) {
              logger.error('Failed to send keep-alive', { sessionId, error: error.message });
              clearInterval(keepAliveInterval);
            }
          }, 5000);

          this.keepAliveIntervals = this.keepAliveIntervals || new Map();
          this.keepAliveIntervals.set(sessionId, keepAliveInterval);
          
          resolve();
        });

        // Handle Settings Applied event
        // Voice Agent sends this after valid settings are received
        connection.on(AgentEvents.SettingsApplied, (data) => {
          try {
            logger.debug('Settings applied', { sessionId, data });
            eventHandlers.onSettingsApplied?.({
              message: 'Voice Agent settings configured successfully'
            });
          } catch (error) {
            logger.error('Error processing settings applied', { sessionId, error: error.message });
          }
        });

        // Handle User Transcription
        connection.on(AgentEvents.UserTranscription, (data) => {
          try {
            logger.debug('Received user transcript', { 
              sessionId, 
              transcript: data.transcript,
              words: data.words?.length || 0
            });

            eventHandlers.onTranscript?.({
              transcript: data.transcript,
              words: data.words || [],
              isFinal: true,
              type: 'user'
            });
          } catch (error) {
            logger.error('Error processing user transcript', { sessionId, error: error.message });
          }
        });

        // Handle Agent Transcription
        connection.on(AgentEvents.AgentTranscription, (data) => {
          try {
            logger.debug('Received agent transcript', { 
              sessionId, 
              transcript: data.transcript,
              words: data.words?.length || 0
            });

            eventHandlers.onTranscript?.({
              transcript: data.transcript,
              words: data.words || [],
              isFinal: true,
              type: 'agent'
            });
          } catch (error) {
            logger.error('Error processing agent transcript', { sessionId, error: error.message });
          }
        });

        // Handle Agent Audio (TTS output)
        connection.on(AgentEvents.AgentAudio, (data) => {
          try {
            logger.debug('Received agent audio', { sessionId, size: data.byteLength || data.length });
            eventHandlers.onAgentAudio?.(data);
          } catch (error) {
            logger.error('Error processing agent audio', { sessionId, error: error.message });
          }
        });

        // Handle Metadata
        connection.on(AgentEvents.Metadata, (data) => {
          logger.debug('Received metadata', { sessionId, requestId: data?.request_id });
        });

        // Handle Error - Both RFC-6455 protocol errors and Deepgram API errors
        connection.on(AgentEvents.Error, (error) => {
          try {
            const errorMessage = error?.message || error?.toString() || 'Unknown error';
            const errorCode = error?.code || 'UNKNOWN_ERROR';
            
            logger.error('Deepgram Voice Agent error', { 
              sessionId, 
              error: errorMessage,
              code: errorCode,
              type: error?.type || 'application'
            });

            // Pass structured error to handler
            eventHandlers.onError?.({
              message: errorMessage,
              code: errorCode,
              type: error?.type || 'application_error',
              error: error
            });
          } catch (processError) {
            logger.error('Error processing Deepgram error', { 
              sessionId, 
              error: processError.message 
            });
          }
        });

        // Handle Close
        connection.on(AgentEvents.Close, () => {
          logger.info('Disconnected from Deepgram Voice Agent API', { sessionId });
          
          // Clear keep-alive interval
          if (this.keepAliveIntervals && this.keepAliveIntervals.has(sessionId)) {
            clearInterval(this.keepAliveIntervals.get(sessionId));
            this.keepAliveIntervals.delete(sessionId);
          }
          
          this.agentConnections.delete(sessionId);
          this.eventHandlers.delete(sessionId);
          eventHandlers.onClose?.();
        });

        // Handle keep_alive
        connection.on(AgentEvents.KeepAlive, () => {
          logger.debug('Keep-alive received', { sessionId });
        });

        // Handle unhandled events (Issue #354 - unrecognized message format)
        connection.on('message', (data) => {
          logger.debug('Unhandled message received', { 
            sessionId, 
            type: typeof data,
            size: data?.length || data?.byteLength || 'unknown'
          });
        });

        // Handle AgentThinking event (Issue #400 - when available)
        // This event may not be fully supported yet, but handler is ready
        try {
          connection.on(AgentEvents.AgentThinking, (data) => {
            logger.debug('Agent is thinking', { sessionId });
            eventHandlers.onAgentThinking?.(data);
          });
        } catch (error) {
          // AgentThinking may not be available yet
          logger.debug('AgentThinking event not available', { sessionId });
        }

      } catch (error) {
        logger.error('Failed to connect to Deepgram Voice Agent', { sessionId, error: error.message });
        reject(error);
      }
    });
  }

  /**
   * Send audio to Deepgram Voice Agent
   * Audio must be linear16 PCM at 16kHz (as per Deepgram requirements)
   * Compatible with Expo Audio recording format
   * 
   * NOTE: As per SDK Issue #366, send() is async and should be awaited
   * However, in high-frequency audio streaming, we fire-and-forget for performance
   * 
   * @param {string} sessionId - User session ID
   * @param {ArrayBuffer|Buffer|Uint8Array} audioBuffer - Audio data (linear16 PCM)
   * @returns {boolean} - True if audio was sent, false otherwise
   */
  sendAudio(sessionId, audioBuffer) {
    const connection = this.agentConnections.get(sessionId);
    if (!connection) {
      logger.warn('Cannot send audio: no active Voice Agent connection', { sessionId });
      return false;
    }

    try {
      // Validate audio buffer
      if (!audioBuffer) {
        logger.warn('Audio buffer is null or undefined', { sessionId });
        return false;
      }

      // Check for zero-byte audio (common Expo issue)
      const byteLength = audioBuffer.byteLength || audioBuffer.length;
      if (byteLength === 0) {
        logger.warn('Zero-byte audio detected, skipping', { sessionId });
        return false;
      }

      // Log audio metrics for debugging Expo integration
      if (byteLength < 160) { // Less than 10ms at 16kHz
        logger.debug('Very small audio chunk', { sessionId, bytes: byteLength, duration: '< 10ms' });
      }

      // Send audio to Deepgram
      // Note: send() is async per SDK #366, but we don't await here for performance
      // In high-frequency streaming, fire-and-forget is necessary
      connection.send(audioBuffer).catch((error) => {
        logger.error('Error sending audio buffer', { 
          sessionId, 
          error: error?.message || error,
          size: byteLength
        });
      });

      logger.debug('Audio sent to Voice Agent', { 
        sessionId, 
        size: byteLength,
        estimatedDuration: `${(byteLength / 32).toFixed(0)}ms`
      });

      return true;
    } catch (error) {
      logger.error('Failed to send audio to Voice Agent', { 
        sessionId, 
        error: error.message,
        errorCode: error.code
      });
      return false;
    }
  }

  /**
   * Update agent configuration during conversation
   * Documented in: /docs/voice-agent-update-prompt
   * @param {string} sessionId - User session ID
   * @param {string} newPrompt - New system prompt
   */
  updatePrompt(sessionId, newPrompt) {
    const connection = this.agentConnections.get(sessionId);
    if (!connection) {
      logger.warn('Cannot update prompt: no active connection', { sessionId });
      return;
    }

    try {
      if (typeof connection.updatePrompt === 'function') {
        connection.updatePrompt({ instructions: newPrompt });
        logger.info('Prompt updated', { sessionId, newPromptLength: newPrompt.length });
      } else {
        logger.warn('updatePrompt method not available on connection', { sessionId });
      }
    } catch (error) {
      logger.error('Failed to update prompt', { sessionId, error: error.message });
    }
  }

  /**
   * Update TTS voice during conversation
   * Documented in: /docs/voice-agent-update-speak
   * @param {string} sessionId - User session ID
   * @param {string} newVoice - New voice model (e.g., 'aura-asteria-en')
   */
  updateSpeak(sessionId, newVoice) {
    const connection = this.agentConnections.get(sessionId);
    if (!connection) {
      logger.warn('Cannot update voice: no active connection', { sessionId });
      return;
    }

    try {
      if (typeof connection.updateSpeak === 'function') {
        connection.updateSpeak({ model: newVoice });
        logger.info('Voice/speak model updated', { sessionId, voice: newVoice });
      } else {
        logger.warn('updateSpeak method not available on connection', { sessionId });
      }
    } catch (error) {
      logger.error('Failed to update speak model', { sessionId, error: error.message });
    }
  }

  /**
   * Inject an agent message (as if the agent generated it)
   * Documented in: /docs/voice-agent-inject-agent-message
   * 
   * Note: Issue #354 - Ensure message format matches SDK expectations
   * 
   * @param {string} sessionId - User session ID
   * @param {string} message - Message to inject as agent response
   */
  injectAgentMessage(sessionId, message) {
    const connection = this.agentConnections.get(sessionId);
    if (!connection) {
      logger.warn('Cannot inject agent message: no active connection', { sessionId });
      return false;
    }

    try {
      if (!message || typeof message !== 'string') {
        logger.warn('Invalid message format for injection', { 
          sessionId, 
          messageType: typeof message,
          messageTruthy: !!message
        });
        return false;
      }

      if (typeof connection.injectAgentMessage === 'function') {
        // Ensure message is properly formatted per SDK expectations
        connection.injectAgentMessage({ message });
        logger.info('Agent message injected', { 
          sessionId, 
          messageLength: message.length 
        });
        return true;
      } else {
        logger.warn('injectAgentMessage method not available on connection', { sessionId });
        return false;
      }
    } catch (error) {
      logger.error('Failed to inject agent message', { 
        sessionId, 
        error: error.message,
        errorCode: error.code
      });
      return false;
    }
  }

  /**
   * Inject a user message (as if the user said it)
   * Documented in: /docs/voice-agent-inject-user-message
   * 
   * Note: Issue #354 - Ensure message format matches SDK expectations
   * 
   * @param {string} sessionId - User session ID
   * @param {string} message - Message to inject as user input
   */
  injectUserMessage(sessionId, message) {
    const connection = this.agentConnections.get(sessionId);
    if (!connection) {
      logger.warn('Cannot inject user message: no active connection', { sessionId });
      return false;
    }

    try {
      if (!message || typeof message !== 'string') {
        logger.warn('Invalid message format for injection', { 
          sessionId, 
          messageType: typeof message,
          messageTruthy: !!message
        });
        return false;
      }

      if (typeof connection.injectUserMessage === 'function') {
        // Ensure message is properly formatted per SDK expectations
        connection.injectUserMessage({ message });
        logger.info('User message injected', { 
          sessionId, 
          messageLength: message.length 
        });
        return true;
      } else {
        logger.warn('injectUserMessage method not available on connection', { sessionId });
        return false;
      }
    } catch (error) {
      logger.error('Failed to inject user message', { 
        sessionId, 
        error: error.message,
        errorCode: error.code
      });
      return false;
    }
  }

  /**
   * Gracefully close Voice Agent connection
   * Follows Deepgram's proper shutdown procedure
   * @param {string} sessionId - User session ID
   */
  disconnect(sessionId) {
    const connection = this.agentConnections.get(sessionId);
    if (connection) {
      try {
        logger.info('Closing Deepgram Voice Agent connection', { sessionId });
        
        // Clear keep-alive interval first
        if (this.keepAliveIntervals && this.keepAliveIntervals.has(sessionId)) {
          clearInterval(this.keepAliveIntervals.get(sessionId));
          this.keepAliveIntervals.delete(sessionId);
          logger.debug('Keep-alive interval cleared', { sessionId });
        }
        
        // Close connection gracefully
        // This sends a proper WebSocket close frame (RFC-6455)
        connection.close();
        
        // Clean up stored references
        this.agentConnections.delete(sessionId);
        this.eventHandlers.delete(sessionId);
        
        logger.info('Voice Agent connection closed successfully', { sessionId });
      } catch (error) {
        logger.error('Error closing Voice Agent connection', { 
          sessionId, 
          error: error.message,
          errorCode: error.code
        });
      }
    }
  }

  /**
   * Check if a session is connected
   * @param {string} sessionId - User session ID
   * @returns {boolean}
   */
  isConnected(sessionId) {
    return this.agentConnections.has(sessionId);
  }

  /**
   * Alias for updateSpeak() - Update TTS voice (backward compatibility)
   * @param {string} sessionId - User session ID
   * @param {string} newVoice - New voice model
   */
  updateVoice(sessionId, newVoice) {
    return this.updateSpeak(sessionId, newVoice);
  }

  /**
   * Disconnect all active connections (for graceful shutdown)
   * Called during server shutdown or process termination
   */
  disconnectAll() {
    logger.info('Disconnecting all Voice Agent sessions', { count: this.agentConnections.size });
    
    try {
      // Disconnect all active agent connections
      for (const [sessionId] of this.agentConnections.entries()) {
        try {
          this.disconnect(sessionId);
        } catch (error) {
          logger.error('Error disconnecting session during shutdown', { 
            sessionId, 
            error: error.message 
          });
        }
      }

      // Clear all keep-alive intervals
      if (this.keepAliveIntervals) {
        for (const [sessionId, interval] of this.keepAliveIntervals.entries()) {
          try {
            clearInterval(interval);
            logger.debug('Cleared keep-alive interval', { sessionId });
          } catch (error) {
            logger.error('Error clearing keep-alive interval', { 
              sessionId, 
              error: error.message 
            });
          }
        }
        this.keepAliveIntervals.clear();
      }

      // Verify cleanup
      if (this.agentConnections.size === 0 && (!this.keepAliveIntervals || this.keepAliveIntervals.size === 0)) {
        logger.info('All Voice Agent sessions disconnected successfully');
      }
    } catch (error) {
      logger.error('Error during full disconnection', { error: error.message });
    }
  }
}

module.exports = new DeepgramService();
