/**
 * Call manager for handling voice call lifecycle.
 *
 * Manages active calls, state transitions, and coordinates between
 * Twilio, STT, TTS, and the Flowly agent.
 */

import { EventEmitter } from 'events';
import { Logger } from 'pino';
import { WebSocket } from 'ws';
import type { CallRecord, CallState, CallEvent, TranscriptEntry, STTResult } from './types.js';
import { TwilioProvider, MediaStreamHandler, createMediaStreamHandler, TwiMLBuilder, gatherSpeechTwiML } from './twilio/index.js';
import { createSTT, type STTProvider } from './stt/index.js';
import { createTTS, type TTSProvider } from './tts/index.js';
import { convertToTwilioAudio } from './audio.js';
import type { Config } from './config.js';

// Pending response handler for agent responses
type ResponseHandler = (text: string) => void;
const pendingResponses: Map<string, ResponseHandler> = new Map();

export interface CallManagerOptions {
  config: Config;
  logger?: Logger;
}

export class CallManager extends EventEmitter {
  private config: Config;
  private logger?: Logger;
  private provider: TwilioProvider;
  private tts: TTSProvider;

  // Active calls by SID
  private calls: Map<string, CallRecord> = new Map();

  // Media streams by call SID
  private streams: Map<string, MediaStreamHandler> = new Map();

  // STT instances by call SID
  private sttInstances: Map<string, STTProvider> = new Map();

  constructor(options: CallManagerOptions) {
    super();
    this.config = options.config;
    this.logger = options.logger;

    // Initialize Twilio provider
    this.provider = new TwilioProvider({
      accountSid: this.config.twilio.accountSid,
      authToken: this.config.twilio.authToken,
      phoneNumber: this.config.twilio.phoneNumber,
      webhookBaseUrl: this.config.webhook.baseUrl,
      logger: this.logger,
    });

    // Initialize TTS
    this.tts = createTTS({
      provider: this.config.tts.provider,
      openaiApiKey: this.config.tts.openaiApiKey,
      deepgramApiKey: this.config.tts.deepgramApiKey,
      voice: this.config.tts.voice,
      model: this.config.tts.model,
      logger: this.logger,
    });
  }

  /**
   * Make a simple outbound call with a message.
   */
  async makeCall(options: {
    to: string;
    message: string;
    metadata?: Record<string, unknown>;
  }): Promise<CallRecord> {
    const { to, message, metadata } = options;

    const call = await this.provider.makeCall({
      to,
      message,
      statusCallback: this.getStatusCallbackUrl(),
      metadata,
    });

    this.calls.set(call.callSid, call);
    call.transcript.push({
      role: 'assistant',
      text: message,
      timestamp: new Date(),
    });

    this.emitEvent({
      callSid: call.callSid,
      eventType: 'state_changed',
      timestamp: new Date(),
      data: { state: call.state, to },
    });

    return call;
  }

  /**
   * Make a conversation call with Media Streams for real-time audio.
   */
  async makeConversationCall(options: {
    to: string;
    greeting: string;
    metadata?: Record<string, unknown>;
  }): Promise<CallRecord> {
    const { to, greeting, metadata } = options;

    // For Media Streams, we use a WebSocket URL
    const wsUrl = this.getMediaStreamUrl();

    const call = await this.provider.makeMediaStreamCall({
      to,
      websocketUrl: wsUrl,
      statusCallback: this.getStatusCallbackUrl(),
      metadata,
    });

    this.calls.set(call.callSid, call);

    // Store greeting to speak when stream connects
    call.metadata._greeting = greeting;

    this.emitEvent({
      callSid: call.callSid,
      eventType: 'state_changed',
      timestamp: new Date(),
      data: { state: call.state, to },
    });

    return call;
  }

  /**
   * Handle new WebSocket connection for Media Stream.
   */
  async handleMediaStream(ws: WebSocket): Promise<void> {
    const stream = createMediaStreamHandler(ws, {
      logger: this.logger,
    });

    stream.on('connected', async (callSid: string, streamSid: string) => {
      this.logger?.info({ callSid, streamSid }, 'Media stream connected');
      this.streams.set(callSid, stream);

      const call = this.calls.get(callSid);
      if (call) {
        call.streamSid = streamSid;
        call.state = 'in-progress';
        call.answeredAt = new Date();

        // Set up STT for this call
        await this.setupSTT(callSid, stream);

        // Speak greeting if set
        const greeting = call.metadata._greeting as string;
        if (greeting) {
          await this.speak(callSid, greeting);
          delete call.metadata._greeting;
        }

        this.emitEvent({
          callSid,
          eventType: 'stream_connected',
          timestamp: new Date(),
          data: { streamSid },
        });
      }
    });

    stream.on('disconnected', (callSid: string) => {
      this.handleStreamDisconnect(callSid);
    });

    stream.on('error', (error) => {
      this.logger?.error({ error }, 'Media stream error');
    });
  }

  /**
   * Set up STT for a call.
   */
  private async setupSTT(callSid: string, stream: MediaStreamHandler): Promise<void> {
    const stt = createSTT({
      provider: this.config.stt.provider,
      deepgramApiKey: this.config.stt.deepgramApiKey,
      openaiApiKey: this.config.stt.openaiApiKey,
      groqApiKey: this.config.stt.groqApiKey,
      language: this.config.stt.language,
      logger: this.logger,
    });

    await stt.connect();
    this.sttInstances.set(callSid, stt);

    // Forward audio from stream to STT
    stream.on('audio', (audio: Buffer) => {
      stt.send(audio);
    });

    // Handle transcription results
    stt.on('final_transcript', (result: STTResult) => {
      this.handleTranscript(callSid, result);
    });

    stt.on('speech_started', () => {
      this.emitEvent({
        callSid,
        eventType: 'speech_started',
        timestamp: new Date(),
        data: {},
      });

      // Barge-in: clear any playing audio
      const activeStream = this.streams.get(callSid);
      if (activeStream?.speaking) {
        activeStream.clearAudio();
        this.emitEvent({
          callSid,
          eventType: 'speech_ended',
          timestamp: new Date(),
          data: { interrupted: true },
        });
      }
    });

    stt.on('error', (error) => {
      this.logger?.error({ error, callSid }, 'STT error');
    });
  }

  /**
   * Handle transcription result.
   */
  private handleTranscript(callSid: string, result: STTResult): void {
    const call = this.calls.get(callSid);
    if (!call || !result.text) return;

    this.logger?.info({ callSid, text: result.text }, 'Transcript received');

    // Add to call transcript
    const entry: TranscriptEntry = {
      role: 'user',
      text: result.text,
      timestamp: new Date(),
      confidence: result.confidence,
    };
    call.transcript.push(entry);

    // Emit transcription event
    this.emitEvent({
      callSid,
      eventType: 'transcription',
      timestamp: new Date(),
      data: {
        text: result.text,
        confidence: result.confidence,
        role: 'user',
      },
    });

    // Send to Flowly agent and speak the response
    this.sendToFlowlyAndRespond(callSid, result.text, call.from);
  }

  /**
   * Send transcription to Flowly agent and speak the response.
   */
  private async sendToFlowlyAndRespond(
    callSid: string,
    text: string,
    from: string
  ): Promise<void> {
    try {
      const gatewayUrl = this.config.flowly.gatewayUrl;

      this.logger?.info({ callSid, text, gatewayUrl }, 'Sending to Flowly agent');

      const response = await fetch(`${gatewayUrl}/api/voice/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          call_sid: callSid,
          from: from,
          text: text,
        }),
      });

      if (!response.ok) {
        throw new Error(`Flowly returned ${response.status}`);
      }

      const data = await response.json() as { response?: string };

      if (data.response) {
        this.logger?.info({ callSid, response: data.response.substring(0, 50) }, 'Got agent response');
        await this.speak(callSid, data.response);
      }
    } catch (error) {
      this.logger?.error({ error, callSid }, 'Failed to send to Flowly');
      // Speak error message
      await this.speak(callSid, "I'm sorry, I couldn't process that. Please try again.");
    }
  }

  /**
   * Speak text on an active call.
   */
  async speak(callSid: string, text: string): Promise<void> {
    const call = this.calls.get(callSid);
    const stream = this.streams.get(callSid);

    if (!call) {
      throw new Error(`Call ${callSid} not found`);
    }

    this.logger?.info({ callSid, text: text.substring(0, 50) }, 'Speaking');

    // Add to transcript
    call.transcript.push({
      role: 'assistant',
      text,
      timestamp: new Date(),
    });

    if (stream?.connected) {
      // Use Media Streams for real-time audio
      const pcmBuffer = await this.tts.synthesize(text);

      // Convert to mu-law frames
      const frames: Buffer[] = [];
      for (const frame of convertToTwilioAudio(pcmBuffer, 24000)) {
        frames.push(frame);
      }

      // Send audio and wait for completion
      await stream.sendAudioFrames(frames);

      this.emitEvent({
        callSid,
        eventType: 'speech_ended',
        timestamp: new Date(),
        data: { role: 'assistant' },
      });
    } else {
      // Fall back to updating call with TwiML
      const twiml = new TwiMLBuilder()
        .say(text)
        .build();

      await this.provider.updateCall({ callSid, twiml });
    }
  }

  /**
   * Speak and wait for user response.
   */
  async speakAndListen(
    callSid: string,
    text: string,
    timeout: number = 30000
  ): Promise<string | null> {
    await this.speak(callSid, text);

    // Wait for transcription
    return new Promise((resolve) => {
      const timeoutId = setTimeout(() => {
        this.off('transcription', handler);
        resolve(null);
      }, timeout);

      const handler = (event: CallEvent) => {
        if (event.callSid === callSid && event.eventType === 'transcription') {
          clearTimeout(timeoutId);
          this.off('transcription', handler);
          resolve(event.data.text as string);
        }
      };

      this.on('transcription', handler);
    });
  }

  /**
   * End a call.
   */
  async endCall(callSid: string, message?: string): Promise<void> {
    const call = this.calls.get(callSid);
    if (!call) {
      throw new Error(`Call ${callSid} not found`);
    }

    // Speak goodbye message if provided
    if (message) {
      await this.speak(callSid, message);
    }

    // End the call
    await this.provider.endCall(callSid);

    // Update state
    call.state = 'completed';
    call.endedAt = new Date();
    if (call.answeredAt) {
      call.durationSeconds = Math.floor(
        (call.endedAt.getTime() - call.answeredAt.getTime()) / 1000
      );
    }

    // Cleanup
    this.handleStreamDisconnect(callSid);

    this.emitEvent({
      callSid,
      eventType: 'state_changed',
      timestamp: new Date(),
      data: { state: 'completed' },
    });
  }

  /**
   * Handle media stream disconnect.
   */
  private handleStreamDisconnect(callSid: string): void {
    // Cleanup STT
    const stt = this.sttInstances.get(callSid);
    if (stt) {
      stt.disconnect();
      this.sttInstances.delete(callSid);
    }

    // Cleanup stream
    const stream = this.streams.get(callSid);
    if (stream) {
      stream.close();
      this.streams.delete(callSid);
    }

    this.emitEvent({
      callSid,
      eventType: 'stream_disconnected',
      timestamp: new Date(),
      data: {},
    });
  }

  /**
   * Handle Twilio status callback.
   */
  async handleStatusCallback(params: Record<string, string>): Promise<void> {
    const callSid = params.CallSid;
    const status = params.CallStatus;
    const direction = params.Direction;

    this.logger?.info({ callSid, status }, 'Status callback received');

    const state = this.provider.parseStatus(status);
    let call = this.calls.get(callSid);

    if (call) {
      const oldState = call.state;
      call.state = state;

      if (state === 'in-progress' && !call.answeredAt) {
        call.answeredAt = new Date();
      }

      if (['completed', 'failed', 'busy', 'no-answer', 'canceled'].includes(state)) {
        call.endedAt = new Date();
        if (call.answeredAt) {
          call.durationSeconds = Math.floor(
            (call.endedAt.getTime() - call.answeredAt.getTime()) / 1000
          );
        }

        if (params.RecordingUrl) {
          call.recordingUrl = params.RecordingUrl;
        }

        // Cleanup
        this.handleStreamDisconnect(callSid);
      }
    } else {
      // Inbound call
      call = {
        callSid,
        accountSid: params.AccountSid,
        direction: direction.includes('inbound') ? 'inbound' : 'outbound',
        from: params.From,
        to: params.To,
        state,
        createdAt: new Date(),
        transcript: [],
        metadata: {},
      };
      this.calls.set(callSid, call);
    }

    this.emitEvent({
      callSid,
      eventType: 'state_changed',
      timestamp: new Date(),
      data: {
        state,
        duration: call.durationSeconds,
      },
    });
  }

  /**
   * Handle Twilio gather callback.
   */
  async handleGatherCallback(params: Record<string, string>): Promise<string> {
    const callSid = params.CallSid;
    const speechResult = params.SpeechResult;
    const digits = params.Digits;
    const confidence = params.Confidence;

    this.logger?.info({ callSid, speechResult, digits }, 'Gather callback received');

    const call = this.calls.get(callSid);
    if (call && speechResult) {
      call.transcript.push({
        role: 'user',
        text: speechResult,
        timestamp: new Date(),
        confidence: confidence ? parseFloat(confidence) : undefined,
      });

      this.emitEvent({
        callSid,
        eventType: 'transcription',
        timestamp: new Date(),
        data: {
          text: speechResult,
          confidence: confidence ? parseFloat(confidence) : undefined,
          role: 'user',
        },
      });
    }

    if (digits) {
      this.emitEvent({
        callSid,
        eventType: 'dtmf',
        timestamp: new Date(),
        data: { digits },
      });
    }

    // Return TwiML to continue gathering
    return gatherSpeechTwiML(
      'I\'m listening.',
      this.getGatherCallbackUrl(),
      { language: this.config.stt.language }
    );
  }

  /**
   * Handle inbound call.
   */
  async handleInboundCall(
    params: Record<string, string>,
    greeting?: string
  ): Promise<string> {
    const callSid = params.CallSid;
    const from = params.From;
    const to = params.To;

    this.logger?.info({ callSid, from }, 'Inbound call received');

    // Create call record
    const call: CallRecord = {
      callSid,
      accountSid: params.AccountSid,
      direction: 'inbound',
      from,
      to,
      state: 'in-progress',
      createdAt: new Date(),
      answeredAt: new Date(),
      transcript: [],
      metadata: {},
    };
    this.calls.set(callSid, call);

    this.emitEvent({
      callSid,
      eventType: 'state_changed',
      timestamp: new Date(),
      data: { state: 'in-progress', from },
    });

    // Use Media Streams for real-time audio
    const wsUrl = this.getMediaStreamUrl();

    // Store greeting for when stream connects
    if (greeting) {
      call.metadata._greeting = greeting;
    }

    return new TwiMLBuilder()
      .connect()
      .stream({ url: wsUrl, track: 'both_tracks' })
      .endConnect()
      .build();
  }

  /**
   * Get call record.
   */
  getCall(callSid: string): CallRecord | undefined {
    return this.calls.get(callSid);
  }

  /**
   * Get all active calls.
   */
  getActiveCalls(): CallRecord[] {
    return Array.from(this.calls.values()).filter(
      (call) => !['completed', 'failed', 'busy', 'no-answer', 'canceled'].includes(call.state)
    );
  }

  /**
   * Verify Twilio signature.
   */
  verifySignature(signature: string, url: string, params: Record<string, string>): boolean {
    return this.provider.verifySignature(signature, url, params);
  }

  /**
   * Emit a call event.
   */
  private emitEvent(event: CallEvent): void {
    this.emit(event.eventType, event);
    this.emit('event', event);
  }

  // URL helpers
  private getStatusCallbackUrl(): string {
    return this.provider.generateWebhookUrl('/voice/status');
  }

  private getGatherCallbackUrl(): string {
    return this.provider.generateWebhookUrl('/voice/gather');
  }

  private getMediaStreamUrl(): string {
    const baseUrl = this.config.webhook.baseUrl || '';
    return baseUrl.replace(/^http/, 'ws') + '/voice/stream';
  }

  /**
   * Cleanup all resources.
   */
  async cleanup(): Promise<void> {
    // End all active calls
    for (const call of this.getActiveCalls()) {
      try {
        await this.endCall(call.callSid);
      } catch (error) {
        this.logger?.error({ error, callSid: call.callSid }, 'Error ending call');
      }
    }

    // Cleanup all streams and STT instances
    for (const callSid of this.streams.keys()) {
      this.handleStreamDisconnect(callSid);
    }

    this.calls.clear();
  }
}

/**
 * Create a call manager instance.
 */
export function createCallManager(options: CallManagerOptions): CallManager {
  return new CallManager(options);
}
