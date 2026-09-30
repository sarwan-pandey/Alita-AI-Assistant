import { useAvatarStore } from '../store/avatarStore';
import { audioService } from './audioService';

class WebSocketService {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.pingInterval = null;
  }

  connect() {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws?token=local_perpetual_admin_token`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('[AvatarWS] Connected to Alita Backend');
        useAvatarStore.getState().setIsConnected(true);
        if (this.reconnectTimer) clearTimeout(this.reconnectTimer);

        // Keepalive ping
        this.pingInterval = setInterval(() => {
          if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 15000);
      };

      this.ws.onmessage = async (event) => {
        // Binary audio stream from backend TTS
        if (event.data instanceof Blob) {
          const arrayBuffer = await event.data.arrayBuffer();
          audioService.playAudioBuffer(arrayBuffer);
          return;
        }

        try {
          const data = JSON.parse(event.data);
          this.handleMessage(data);
        } catch (e) {
          console.warn('[AvatarWS] Unparsed message:', event.data);
        }
      };

      this.ws.onclose = () => {
        console.log('[AvatarWS] Disconnected, scheduling reconnect...');
        useAvatarStore.getState().setIsConnected(false);
        if (this.pingInterval) clearInterval(this.pingInterval);
        this.reconnectTimer = setTimeout(() => this.connect(), 3000);
      };

      this.ws.onerror = (err) => {
        console.warn('[AvatarWS] Error:', err);
      };
    } catch (e) {
      console.warn('[AvatarWS] Connection error:', e);
      this.reconnectTimer = setTimeout(() => this.connect(), 3000);
    }
  }

  handleMessage(data) {
    if (data.type === 'pong') return;

    if (data.type === 'stream_token') {
      useAvatarStore.getState().setAssistantResponse(data.full_text || data.token);
      useAvatarStore.getState().setStatus('thinking');
    } else if (data.type === 'assistant_reply' || data.type === 'response') {
      const text = data.text || data.content || '';
      useAvatarStore.getState().setAssistantResponse(text);
      
      // If backend sends audio URL or audio base64:
      if (data.audio_base64) {
        const binary = atob(data.audio_base64);
        const len = binary.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
        audioService.playAudioBuffer(bytes.buffer);
      } else if (data.speak !== false && text) {
        // Trigger voice synthesis
        audioService.speakText(text);
      }
    } else if (data.type === 'status_change') {
      if (data.status) useAvatarStore.getState().setStatus(data.status);
      if (data.emotion) useAvatarStore.getState().setEmotion(data.emotion);
    }
  }

  sendMessage(text) {
    if (!text.trim()) return;

    useAvatarStore.getState().setTranscription(text);
    useAvatarStore.getState().setStatus('thinking');
    useAvatarStore.getState().setEmotion('thinking');

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'user_message',
        message: text,
        timestamp: Date.now()
      }));
    } else {
      // Local fallback simulation if backend is offline
      setTimeout(() => {
        const fallbackReply = `I received your message: "${text}". I am functioning smoothly!`;
        useAvatarStore.getState().setAssistantResponse(fallbackReply);
        audioService.speakText(fallbackReply);
      }, 750);
    }
  }
}

export const wsService = new WebSocketService();
