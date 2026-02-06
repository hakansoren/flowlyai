/**
 * STT (Speech-to-Text) provider factory.
 */

import { EventEmitter } from 'events';
import { Logger } from 'pino';
import { DeepgramSTT, createDeepgramSTT } from './deepgram.js';
import { OpenAISTT, createOpenAISTT } from './openai.js';
import type { STTResult } from '../types.js';

export type STTProvider = DeepgramSTT | OpenAISTT;

export interface STTOptions {
  provider: 'deepgram' | 'openai';
  deepgramApiKey?: string;
  openaiApiKey?: string;
  language?: string;
  logger?: Logger;
}

/**
 * Create an STT provider based on configuration.
 */
export function createSTT(options: STTOptions): STTProvider {
  switch (options.provider) {
    case 'deepgram':
      if (!options.deepgramApiKey) {
        throw new Error('Deepgram API key is required');
      }
      return createDeepgramSTT({
        apiKey: options.deepgramApiKey,
        language: options.language,
        logger: options.logger,
      });

    case 'openai':
      if (!options.openaiApiKey) {
        throw new Error('OpenAI API key is required');
      }
      return createOpenAISTT({
        apiKey: options.openaiApiKey,
        language: options.language,
        logger: options.logger,
      });

    default:
      throw new Error(`Unknown STT provider: ${options.provider}`);
  }
}

export { DeepgramSTT, OpenAISTT, STTResult };
