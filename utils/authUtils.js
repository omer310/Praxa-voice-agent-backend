const jwt = require('jsonwebtoken');
const config = require('../config/config');
const logger = require('./logger');

class AuthUtils {
  /**
   * Generate a JWT token for a user session
   * @param {Object} payload - Data to encode in token
   * @param {string} payload.userId - User ID
   * @param {string} payload.sessionId - Session ID
   * @returns {string} JWT token
   */
  generateToken(payload) {
    try {
      const token = jwt.sign(payload, config.jwtSecret, {
        expiresIn: config.jwtExpiry,
        algorithm: 'HS256'
      });
      logger.debug('JWT token generated', { userId: payload.userId });
      return token;
    } catch (error) {
      logger.error('Token generation failed', { error: error.message });
      throw error;
    }
  }

  /**
   * Verify and decode a JWT token
   * @param {string} token - JWT token to verify
   * @returns {Object} Decoded token payload
   * @throws {Error} If token is invalid or expired
   */
  verifyToken(token) {
    try {
      const decoded = jwt.verify(token, config.jwtSecret, {
        algorithms: ['HS256']
      });
      logger.debug('JWT token verified', { userId: decoded.userId });
      return decoded;
    } catch (error) {
      logger.warn('Token verification failed', { error: error.message });
      throw error;
    }
  }

  /**
   * Extract token from Authorization header
   * @param {string} authHeader - Authorization header value
   * @returns {string|null} Token if found, null otherwise
   */
  extractTokenFromHeader(authHeader) {
    if (!authHeader) return null;
    
    const parts = authHeader.split(' ');
    if (parts.length !== 2 || parts[0] !== 'Bearer') {
      return null;
    }
    
    return parts[1];
  }

  /**
   * Create a session payload
   * @param {string} userId - User ID
   * @returns {Object} Session payload
   */
  createSessionPayload(userId) {
    const sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    return {
      userId,
      sessionId,
      createdAt: new Date().toISOString(),
      type: 'voice_session'
    };
  }
}

module.exports = new AuthUtils();

