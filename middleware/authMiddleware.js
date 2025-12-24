const authUtils = require('../utils/authUtils');
const logger = require('../utils/logger');

/**
 * Middleware to verify JWT token from Authorization header
 * @param {Object} req - Express request object
 * @param {Object} res - Express response object
 * @param {Function} next - Next middleware function
 */
const verifyJWT = (req, res, next) => {
  try {
    const authHeader = req.headers.authorization;
    const token = authUtils.extractTokenFromHeader(authHeader);

    if (!token) {
      logger.warn('Missing or invalid Authorization header');
      return res.status(401).json({ error: 'Missing or invalid Authorization header' });
    }

    const decoded = authUtils.verifyToken(token);
    req.user = decoded;
    req.sessionId = decoded.sessionId;
    
    next();
  } catch (error) {
    logger.error('JWT verification failed', { error: error.message });
    res.status(401).json({ error: 'Unauthorized: Invalid or expired token' });
  }
};

/**
 * Middleware to verify JWT token from socket.io handshake auth
 * @param {Object} socket - Socket.io socket object
 * @param {Function} next - Next middleware function
 */
const verifySocketJWT = (socket, next) => {
  try {
    const token = socket.handshake.auth.token;

    if (!token) {
      logger.warn('Missing token in socket auth', { socketId: socket.id });
      return next(new Error('Missing authentication token'));
    }

    const decoded = authUtils.verifyToken(token);
    socket.user = decoded;
    socket.sessionId = decoded.sessionId;
    
    logger.debug('Socket authenticated', { userId: decoded.userId, socketId: socket.id });
    next();
  } catch (error) {
    logger.error('Socket JWT verification failed', { error: error.message, socketId: socket.id });
    next(new Error('Unauthorized: Invalid or expired token'));
  }
};

module.exports = {
  verifyJWT,
  verifySocketJWT
};

