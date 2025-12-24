const express = require('express');
const voiceController = require('../controllers/voiceController');
const { verifyJWT } = require('../middleware/authMiddleware');
const logger = require('../utils/logger');

const router = express.Router();

/**
 * POST /api/session/start
 * Start a new voice session for a user
 * 
 * Request body: { userId: string }
 * Response: { sessionId: string, token: string, message: string }
 */
router.post('/start', (req, res) => {
  try {
    const { userId } = req.body;

    if (!userId) {
      logger.warn('Session start request missing userId');
      return res.status(400).json({ error: 'userId is required' });
    }

    voiceController.startSession(userId)
      .then(sessionInfo => {
        logger.info('Session start response sent', { 
          userId, 
          sessionId: sessionInfo.sessionId 
        });
        res.json(sessionInfo);
      })
      .catch(error => {
        logger.error('Session start failed', { userId, error: error.message });
        res.status(500).json({ error: 'Failed to start session' });
      });
  } catch (error) {
    logger.error('Unexpected error in session start', { error: error.message });
    res.status(500).json({ error: 'Internal server error' });
  }
});

/**
 * GET /api/session/status
 * Check the status of an active session
 * 
 * Headers: Authorization: Bearer <token>
 * Response: { sessionId: string, status: string, isConnectedToDeepgram: boolean }
 */
router.get('/status', verifyJWT, (req, res) => {
  try {
    const { sessionId } = req;

    const session = voiceController.getSession(sessionId);

    if (!session) {
      logger.warn('Session not found', { sessionId });
      return res.status(404).json({ error: 'Session not found' });
    }

    res.json({
      sessionId,
      status: session.status,
      isConnectedToDeepgram: session.isConnectedToDeepgram,
      startedAt: session.startedAt,
      transcriptCount: session.transcripts.length
    });
  } catch (error) {
    logger.error('Session status check failed', { error: error.message });
    res.status(500).json({ error: 'Failed to check session status' });
  }
});

/**
 * POST /api/session/end
 * End an active voice session
 * 
 * Headers: Authorization: Bearer <token>
 * Response: { message: string, sessionId: string }
 */
router.post('/end', verifyJWT, (req, res) => {
  try {
    const { sessionId } = req;

    voiceController.endSession(sessionId);

    logger.info('Session ended via API', { sessionId });

    res.json({
      message: 'Session ended successfully',
      sessionId
    });
  } catch (error) {
    logger.error('Session end failed', { error: error.message });
    res.status(500).json({ error: 'Failed to end session' });
  }
});

/**
 * GET /api/session/active-count
 * Get count of active sessions (for monitoring)
 * 
 * Response: { activeSessionCount: number }
 */
router.get('/active-count', (req, res) => {
  try {
    const count = voiceController.getActiveSessionCount();
    res.json({ activeSessionCount: count });
  } catch (error) {
    logger.error('Failed to get active session count', { error: error.message });
    res.status(500).json({ error: 'Failed to get session count' });
  }
});

module.exports = router;

