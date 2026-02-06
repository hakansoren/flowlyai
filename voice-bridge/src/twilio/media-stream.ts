/**
 * Twilio Media Stream handler for real-time bidirectional audio.
 *
 * Handles WebSocket connection from Twilio for streaming audio.
 */

import { WebSocket } from 'ws';
import { EventEmitter } from 'events';
import { Logger } from 'pino';
import type { TwilioMediaMessage, TwilioOutboundMessage } from '../types.js';
import { convertFromTwilioAudio, TWILIO_BYTES_PER_FRAME } from '../audio.js';

export interface MediaStreamOptions {
  logger?: Logger;
  onAudio?: (audio: Buffer) => void;
  onConnected?: (callSid: string, streamSid: string) => void;
  onDisconnected?: (callSid: string) => void;
}

export class MediaStreamHandler extends EventEmitter {
  private ws: WebSocket;
  private logger?: Logger;
  private streamSid: string | null = null;
  private callSid: string | null = null;
  private audioBuffer: Buffer[] = [];
  private markCounter = 0;
  private pendingMarks: Map<string, () => void> = new Map();
  private isSpeaking = false;

  constructor(ws: WebSocket, options: MediaStreamOptions = {}) {
    super();
    this.ws = ws;
    this.logger = options.logger;

    this.setupHandlers();

    if (options.onAudio) {
      this.on('audio', options.onAudio);
    }
    if (options.onConnected) {
      this.on('connected', options.onConnected);
    }
    if (options.onDisconnected) {
      this.on('disconnected', options.onDisconnected);
    }
  }

  /**
   * Set up WebSocket message handlers.
   */
  private setupHandlers(): void {
    this.ws.on('message', (data: Buffer) => {
      try {
        const message: TwilioMediaMessage = JSON.parse(data.toString());
        this.handleMessage(message);
      } catch (error) {
        this.logger?.error({ error }, 'Failed to parse media stream message');
      }
    });

    this.ws.on('close', () => {
      this.logger?.info({ callSid: this.callSid }, 'Media stream closed');
      this.emit('disconnected', this.callSid);
    });

    this.ws.on('error', (error) => {
      this.logger?.error({ error }, 'Media stream error');
      this.emit('error', error);
    });
  }

  /**
   * Handle incoming Twilio media stream message.
   */
  private handleMessage(message: TwilioMediaMessage): void {
    switch (message.event) {
      case 'connected':
        this.logger?.debug('Media stream connected (waiting for start)');
        break;

      case 'start':
        this.handleStart(message);
        break;

      case 'media':
        this.handleMedia(message);
        break;

      case 'stop':
        this.handleStop(message);
        break;

      case 'mark':
        this.handleMark(message);
        break;

      default:
        this.logger?.debug({ event: message.event }, 'Unknown media stream event');
    }
  }

  /**
   * Handle stream start message.
   */
  private handleStart(message: TwilioMediaMessage): void {
    if (!message.start) return;

    this.streamSid = message.start.streamSid;
    this.callSid = message.start.callSid;

    this.logger?.info(
      {
        callSid: this.callSid,
        streamSid: this.streamSid,
        tracks: message.start.tracks,
        mediaFormat: message.start.mediaFormat,
      },
      'Media stream started'
    );

    this.emit('connected', this.callSid, this.streamSid);
  }

  /**
   * Handle incoming audio media.
   */
  private handleMedia(message: TwilioMediaMessage): void {
    if (!message.media) return;

    // Decode base64 mu-law audio
    const audioData = Buffer.from(message.media.payload, 'base64');
    this.audioBuffer.push(audioData);

    // Emit audio in batches (e.g., every 200ms = 10 frames)
    if (this.audioBuffer.length >= 10) {
      this.flushAudioBuffer();
    }
  }

  /**
   * Flush accumulated audio buffer.
   */
  private flushAudioBuffer(): void {
    if (this.audioBuffer.length === 0) return;

    // Convert mu-law to PCM at 16kHz for STT
    const pcmAudio = convertFromTwilioAudio(this.audioBuffer, 16000);
    this.audioBuffer = [];

    this.emit('audio', pcmAudio);
  }

  /**
   * Handle stream stop message.
   */
  private handleStop(message: TwilioMediaMessage): void {
    this.logger?.info({ callSid: this.callSid }, 'Media stream stopped');

    // Flush any remaining audio
    this.flushAudioBuffer();

    this.emit('disconnected', this.callSid);
  }

  /**
   * Handle mark message (audio playback completed).
   */
  private handleMark(message: TwilioMediaMessage): void {
    if (!message.mark) return;

    const markName = message.mark.name;
    this.logger?.debug({ markName }, 'Mark received');

    // Resolve pending mark promise
    const resolver = this.pendingMarks.get(markName);
    if (resolver) {
      resolver();
      this.pendingMarks.delete(markName);
    }

    // Check if this was the last mark (speaking finished)
    if (this.pendingMarks.size === 0 && this.isSpeaking) {
      this.isSpeaking = false;
      this.emit('speaking_finished');
    }

    this.emit('mark', markName);
  }

  /**
   * Send audio to Twilio (for playback to caller).
   * Audio should be mu-law encoded, base64 string.
   */
  sendAudio(mulawBase64: string): void {
    if (!this.streamSid) {
      this.logger?.warn('Cannot send audio: stream not connected');
      return;
    }

    const message: TwilioOutboundMessage = {
      event: 'media',
      streamSid: this.streamSid,
      media: {
        payload: mulawBase64,
      },
    };

    this.ws.send(JSON.stringify(message));
  }

  /**
   * Send audio frames (array of mu-law buffers).
   * Returns a promise that resolves when playback is complete.
   */
  async sendAudioFrames(frames: Buffer[]): Promise<void> {
    if (!this.streamSid || frames.length === 0) return;

    this.isSpeaking = true;
    const markName = `mark_${++this.markCounter}`;

    // Send all audio frames
    for (const frame of frames) {
      this.sendAudio(frame.toString('base64'));
    }

    // Send mark to know when playback is done
    const markMessage: TwilioOutboundMessage = {
      event: 'mark',
      streamSid: this.streamSid,
      mark: {
        name: markName,
      },
    };
    this.ws.send(JSON.stringify(markMessage));

    // Wait for mark acknowledgment
    return new Promise((resolve) => {
      this.pendingMarks.set(markName, resolve);
    });
  }

  /**
   * Clear the audio queue (for barge-in support).
   */
  clearAudio(): void {
    if (!this.streamSid) return;

    const message: TwilioOutboundMessage = {
      event: 'clear',
      streamSid: this.streamSid,
    };

    this.ws.send(JSON.stringify(message));
    this.pendingMarks.clear();
    this.isSpeaking = false;

    this.logger?.debug('Audio cleared');
  }

  /**
   * Check if currently speaking.
   */
  get speaking(): boolean {
    return this.isSpeaking;
  }

  /**
   * Get the stream SID.
   */
  get sid(): string | null {
    return this.streamSid;
  }

  /**
   * Get the call SID.
   */
  get call(): string | null {
    return this.callSid;
  }

  /**
   * Check if connected.
   */
  get connected(): boolean {
    return this.streamSid !== null && this.ws.readyState === WebSocket.OPEN;
  }

  /**
   * Close the WebSocket connection.
   */
  close(): void {
    this.flushAudioBuffer();
    this.ws.close();
  }
}

/**
 * Create a media stream handler.
 */
export function createMediaStreamHandler(
  ws: WebSocket,
  options?: MediaStreamOptions
): MediaStreamHandler {
  return new MediaStreamHandler(ws, options);
}
