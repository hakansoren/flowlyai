/**
 * ElevenLabs STT (Speech-to-Text) provider.
 *
 * Uses ElevenLabs' Realtime Speech-to-Text WebSocket API.
 * Provides streaming transcription with low latency.
 */

import { EventEmitter } from 'events';
import { Logger } from 'pino';
import WebSocket from 'ws';
import type { STTResult } from '../types.js';

export interface ElevenLabsSTTOptions {
  apiKey: string;
  language?: string;
  model?: string;
  logger?: Logger;
}

interface ElevenLabsMessage {
  type: string;
  text?: string;
  is_final?: boolean;
  confidence?: number;
  language?: string;
  error?: string;
}

export class ElevenLabsSTT extends EventEmitter {
  private apiKey: string;
  private language: string;
  private model: string;
  private logger?: Logger;
  private ws: WebSocket | null = null;
  private isConnected = false;
  private reconnectAttempts = 0;
  private readonly MAX_RECONNECT_ATTEMPTS = 3;
  private pendingAudio: Buffer[] = [];

  constructor(options: ElevenLabsSTTOptions) {
    super();
    this.apiKey = options.apiKey;
    // ElevenLabs uses ISO 639-1 codes (e.g., 'en', 'tr')
    const lang = options.language || 'en';
    this.language = lang.split('-')[0];
    this.model = options.model || 'scribe_v1'; // ElevenLabs Scribe model
    this.logger = options.logger;
  }

  /**
   * Connect to the ElevenLabs STT WebSocket.
   */
  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        // Build WebSocket URL with parameters
        const params = new URLSearchParams({
          model_id: this.model,
          language_code: this.language,
          sample_rate: '16000', // We send 16kHz audio
          encoding: 'pcm_s16le', // 16-bit signed PCM
        });

        const url = `wss://api.elevenlabs.io/v1/speech-to-text/stream?${params.toString()}`;

        this.ws = new WebSocket(url, {
          headers: {
            'xi-api-key': this.apiKey,
          },
        });

        this.ws.on('open', () => {
          this.isConnected = true;
          this.reconnectAttempts = 0;
          this.logger?.info('ElevenLabs STT WebSocket connected');

          // Send any pending audio
          for (const audio of this.pendingAudio) {
            this.ws?.send(audio);
          }
          this.pendingAudio = [];

          this.emit('connected');
          resolve();
        });

        this.ws.on('message', (data: Buffer) => {
          try {
            const message: ElevenLabsMessage = JSON.parse(data.toString());
            this.handleMessage(message);
          } catch (error) {
            this.logger?.error({ error }, 'Failed to parse ElevenLabs STT message');
          }
        });

        this.ws.on('close', (code, reason) => {
          this.isConnected = false;
          this.logger?.info({ code, reason: reason.toString() }, 'ElevenLabs STT WebSocket closed');

          // Try to reconnect if not intentional close
          if (code !== 1000 && this.reconnectAttempts < this.MAX_RECONNECT_ATTEMPTS) {
            this.reconnectAttempts++;
            this.logger?.info({ attempt: this.reconnectAttempts }, 'Attempting to reconnect...');
            setTimeout(() => this.connect(), 1000 * this.reconnectAttempts);
          }

          this.emit('disconnected');
        });

        this.ws.on('error', (error) => {
          this.logger?.error({ error }, 'ElevenLabs STT WebSocket error');
          this.emit('error', error);
          if (!this.isConnected) {
            reject(error);
          }
        });
      } catch (error) {
        this.logger?.error({ error }, 'Failed to connect to ElevenLabs STT');
        reject(error);
      }
    });
  }

  /**
   * Handle incoming WebSocket messages.
   */
  private handleMessage(message: ElevenLabsMessage): void {
    switch (message.type) {
      case 'transcript':
        if (message.text) {
          const result: STTResult = {
            text: message.text,
            confidence: message.confidence || 1.0,
            isFinal: message.is_final || false,
          };

          this.logger?.debug({ text: message.text, isFinal: message.is_final }, 'ElevenLabs transcript');

          this.emit('transcript', result);

          if (result.isFinal) {
            this.emit('final_transcript', result);
          }
        }
        break;

      case 'error':
        this.logger?.error({ error: message.error }, 'ElevenLabs STT error');
        this.emit('error', new Error(message.error || 'Unknown ElevenLabs STT error'));
        break;

      case 'session_started':
        this.logger?.debug('ElevenLabs STT session started');
        break;

      case 'session_ended':
        this.logger?.debug('ElevenLabs STT session ended');
        break;

      default:
        this.logger?.debug({ type: message.type }, 'Unknown ElevenLabs message type');
    }
  }

  /**
   * Send audio data for transcription.
   * Audio should be 16kHz 16-bit PCM.
   */
  send(audioData: Buffer): void {
    if (!this.isConnected || !this.ws) {
      // Buffer audio if not yet connected
      this.pendingAudio.push(audioData);
      return;
    }

    try {
      // ElevenLabs expects raw audio bytes
      this.ws.send(audioData);
    } catch (error) {
      this.logger?.error({ error }, 'Failed to send audio to ElevenLabs STT');
    }
  }

  /**
   * Signal end of audio stream and request final results.
   */
  finalize(): void {
    if (this.ws && this.isConnected) {
      try {
        // Send end-of-stream message
        this.ws.send(JSON.stringify({ type: 'end_of_stream' }));
      } catch (error) {
        this.logger?.error({ error }, 'Failed to finalize ElevenLabs STT');
      }
    }
  }

  /**
   * Disconnect from the STT provider.
   */
  disconnect(): void {
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    this.isConnected = false;
    this.pendingAudio = [];
    this.logger?.info('ElevenLabs STT disconnected');
    this.emit('disconnected');
  }

  /**
   * Check if connected.
   */
  get connected(): boolean {
    return this.isConnected;
  }
}

/**
 * Create an ElevenLabs STT instance.
 */
export function createElevenLabsSTT(options: ElevenLabsSTTOptions): ElevenLabsSTT {
  return new ElevenLabsSTT(options);
}
