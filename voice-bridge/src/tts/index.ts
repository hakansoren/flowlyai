/**
 * TTS (Text-to-Speech) provider factory.
 */

import { Logger } from 'pino';
import { OpenAITTS, createOpenAITTS, OPENAI_VOICES, OPENAI_TTS_MODELS } from './openai.js';

export type TTSProvider = OpenAITTS;

export interface TTSOptions {
  provider: 'openai' | 'twilio';
  openaiApiKey?: string;
  voice?: string;
  model?: string;
  speed?: number;
  logger?: Logger;
}

/**
 * Create a TTS provider based on configuration.
 */
export function createTTS(options: TTSOptions): TTSProvider {
  switch (options.provider) {
    case 'openai':
      if (!options.openaiApiKey) {
        throw new Error('OpenAI API key is required');
      }
      return createOpenAITTS({
        apiKey: options.openaiApiKey,
        voice: options.voice,
        model: options.model,
        speed: options.speed,
        logger: options.logger,
      });

    case 'twilio':
      // Twilio TTS is handled via TwiML, not a separate provider
      // For now, fall back to OpenAI
      throw new Error('Twilio TTS should be handled via TwiML <Say> verb');

    default:
      throw new Error(`Unknown TTS provider: ${options.provider}`);
  }
}

export { OpenAITTS, OPENAI_VOICES, OPENAI_TTS_MODELS };
