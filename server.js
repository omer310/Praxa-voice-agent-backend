const express = require('express');
const http = require('http');
const { Server: SocketIOServer } = require('socket.io');
const config = require('./config/config');
const logger = require('./utils/logger');
const authRoutes = require('./routes/authRoutes');
const voiceRoutes = require('./routes/voiceRoutes');
const { verifySocketJWT } = require('./middleware/authMiddleware');
const voiceController = require('./controllers/voiceController');
const { initializeSocketHandlers } = require('./utils/socketHandlers');

// Initialize Express app
const app = express();
const server = http.createServer(app);

// Initialize Socket.io
const io = new SocketIOServer(server, {
  cors: {
    origin: config.corsOrigins,
    methods: ['GET', 'POST'],
    credentials: true
  },
  transports: ['websocket', 'polling']
});

// Middleware
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Request logging middleware
app.use((req, res, next) => {
  logger.debug(`${req.method} ${req.path}`);
  next();
});

// API Routes
app.use('/api/auth', authRoutes);
app.use('/api/session', voiceRoutes);

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    activeSessions: voiceController.getActiveSessionCount()
  });
});

// 404 handler
app.use((req, res) => {
  res.status(404).json({ error: 'Not found' });
});

// Error handler
app.use((err, req, res, next) => {
  logger.error('Unhandled error', { error: err.message, path: req.path });
  res.status(500).json({ error: 'Internal server error' });
});

// Socket.io middleware - Verify JWT before allowing connection
io.use((socket, next) => {
  verifySocketJWT(socket, next);
});

// Initialize all socket event handlers
initializeSocketHandlers(io);

// Graceful shutdown handler
process.on('SIGTERM', () => {
  logger.info('SIGTERM received, shutting down gracefully');
  voiceController.gracefulShutdown();
  server.close(() => {
    logger.info('Server closed');
    process.exit(0);
  });
});

process.on('SIGINT', () => {
  logger.info('SIGINT received, shutting down gracefully');
  voiceController.gracefulShutdown();
  server.close(() => {
    logger.info('Server closed');
    process.exit(0);
  });
});

// Start server
const PORT = config.port;
server.listen(PORT, () => {
  logger.info(`Server listening on port ${PORT}`, {
    env: config.nodeEnv,
    corsOrigins: config.corsOrigins
  });
});

module.exports = { app, server, io };

