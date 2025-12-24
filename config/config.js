require('dotenv').config();

const config = {
  // Server Configuration
  port: process.env.PORT || 3000,
  nodeEnv: process.env.NODE_ENV || 'development',
  logLevel: process.env.LOG_LEVEL || 'info',

  // API Keys
  deepgramApiKey: process.env.DEEPGRAM_API_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,

  // JWT Configuration
  jwtSecret: process.env.JWT_SECRET,
  jwtExpiry: process.env.JWT_EXPIRY || '24h',

  // Deepgram Configuration
  deepgramModel: process.env.DEEPGRAM_MODEL || 'nova-2',
  deepgramVoiceModel: process.env.DEEPGRAM_VOICE_MODEL || 'aura-asteria-en',
  deepgramEndpoint: 'wss://agent.deepgram.com/v1/agent/converse',

  // CORS Configuration
  corsOrigins: process.env.CORS_ORIGINS ? process.env.CORS_ORIGINS.split(',') : ['http://localhost:8081', 'http://localhost:3000'],

  // Validation
  validate() {
    const required = ['deepgramApiKey', 'openaiApiKey', 'jwtSecret'];
    const missing = required.filter(key => !this[key]);
    
    if (missing.length > 0) {
      throw new Error(`Missing required environment variables: ${missing.join(', ')}`);
    }
  }
};

// Validate configuration on load
config.validate();

module.exports = config;

