require('dotenv').config();

const config = {
  // Server Configuration
  port: process.env.PORT || 3000,
  nodeEnv: process.env.NODE_ENV || 'development',
  logLevel: process.env.LOG_LEVEL || 'info',

  // API Keys
  deepgramApiKey: process.env.DEEPGRAM_API_KEY,
  openaiApiKey: process.env.OPENAI_API_KEY,
  deepgramEndpoint: process.env.DEEPGRAM_ENDPOINT || 'api.deepgram.com', // EU: api.eu.deepgram.com

  // JWT Configuration
  jwtSecret: process.env.JWT_SECRET,
  jwtExpiry: process.env.JWT_EXPIRY || '24h',

  // Deepgram Voice Agent Configuration
  deepgramListenModel: process.env.DEEPGRAM_LISTEN_MODEL || 'nova-3',
  deepgramLLMProvider: process.env.DEEPGRAM_LLM_PROVIDER || 'open_ai', // 'open_ai', 'anthropic', 'google', 'groq'
  deepgramLLMModel: process.env.DEEPGRAM_LLM_MODEL || 'gpt-4o-mini',
  // Updated voice models (Aura-2 now supports: en, fr, de, it, nl, ja)
  deepgramVoiceModel: process.env.DEEPGRAM_VOICE_MODEL || 'aura-2-en-neural', // Aura-2 with multilingual support
  deepgramSystemPrompt: process.env.DEEPGRAM_SYSTEM_PROMPT || 'You are a helpful voice assistant. Keep responses concise and natural for voice conversation.',
  deepgramGreeting: process.env.DEEPGRAM_GREETING || 'Hello! How can I help you today?',
  deepgramEotTimeout: parseInt(process.env.DEEPGRAM_EOT_TIMEOUT || '5000'), // End-of-turn timeout in ms (default 5000, max 10000)

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

