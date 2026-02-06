/**
 * TTS (Text-to-Speech) provider factory.
 */

import { Logger } from 'pino';
import { OpenAITTS, createOpenAITTS, OPENAI_VOICES, OPENAI_TTS_MODELS } from './openai.js';
import { DeepgramTTS, createDeepgramTTS, DEEPGRAM_VOICES } from './deepgram.js';

export type TTSProvider = OpenAITTS | DeepgramTTS;

export interface TTSOptions {
  provider: 'openai' | 'deepgram';
  openaiApiKey?: string;
  deepgramApiKey?: string;
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
        throw new Error('OpenAI API key is required for TTS');
      }
      return createOpenAITTS({
        apiKey: options.openaiApiKey,
        voice: options.voice,
        model: options.model,
        speed: options.speed,
        logger: options.logger,
      });

    case 'deepgram':
      if (!options.deepgramApiKey) {
        throw new Error('Deepgram API key is required for TTS');
      }
      return createDeepgramTTS({
        apiKey: options.deepgramApiKey,
        voice: options.voice,
        logger: options.logger,
      });

    default:
      throw new Error(`Unknown TTS provider: ${options.provider}`);
  }
}

export { OpenAITTS, DeepgramTTS, OPENAI_VOICES, OPENAI_TTS_MODELS, DEEPGRAM_VOICES };
