const config = require('../config/config');

const LOG_LEVELS = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3
};

class Logger {
  constructor() {
    this.level = LOG_LEVELS[config.logLevel] || LOG_LEVELS.info;
  }

  _log(level, message, meta = {}) {
    const timestamp = new Date().toISOString();
    const levelStr = level.toUpperCase().padEnd(5);
    const output = {
      timestamp,
      level: levelStr,
      message,
      ...meta
    };

    if (LOG_LEVELS[level] >= this.level) {
      console.log(JSON.stringify(output));
    }
  }

  debug(message, meta) {
    this._log('debug', message, meta);
  }

  info(message, meta) {
    this._log('info', message, meta);
  }

  warn(message, meta) {
    this._log('warn', message, meta);
  }

  error(message, meta) {
    this._log('error', message, meta);
  }
}

module.exports = new Logger();

