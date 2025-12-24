const express = require('express');
const authUtils = require('../utils/authUtils');
const logger = require('../utils/logger');

const router = express.Router();

/**
 * POST /api/auth/token
 * Generate a JWT token for a user
 * 
 * Request body: { userId: string }
 * Response: { token: string, expiresIn: string }
 */
router.post('/token', (req, res) => {
  try {
    const { userId } = req.body;

    if (!userId) {
      logger.warn('Token request missing userId');
      return res.status(400).json({ error: 'userId is required' });
    }

    const payload = authUtils.createSessionPayload(userId);
    const token = authUtils.generateToken(payload);

    logger.info('Token generated', { userId, sessionId: payload.sessionId });

    res.json({
      token,
      sessionId: payload.sessionId,
      expiresIn: '24h',
      type: 'Bearer'
    });
  } catch (error) {
    logger.error('Token generation failed', { error: error.message });
    res.status(500).json({ error: 'Failed to generate token' });
  }
});

/**
 * GET /api/auth/verify
 * Verify JWT token validity
 * 
 * Headers: Authorization: Bearer <token>
 * Response: { valid: boolean, payload: object }
 */
router.get('/verify', (req, res) => {
  try {
    const authHeader = req.headers.authorization;
    const token = authUtils.extractTokenFromHeader(authHeader);

    if (!token) {
      return res.status(401).json({ valid: false, error: 'Missing or invalid Authorization header' });
    }

    const decoded = authUtils.verifyToken(token);
    
    logger.debug('Token verified', { userId: decoded.userId });

    res.json({
      valid: true,
      payload: decoded
    });
  } catch (error) {
    logger.warn('Token verification failed', { error: error.message });
    res.status(401).json({ 
      valid: false, 
      error: 'Invalid or expired token' 
    });
  }
});

module.exports = router;

