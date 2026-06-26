export type ConnectionState =
  | "disconnected"
  | "connecting"
  | "ready"
  | "thinking"
  | "speaking"
  | "error";

export interface DisplayText {
  text: string;
  name?: string;
  avatar?: string;
}

export interface BackendMessage {
  type?: string;
  audio?: string;
  display_text?: DisplayText;
  server_perf?: {
    turn_id?: string;
    elapsed_ms?: number;
  };
  text?: string;
  message?: string;
  success?: boolean;
  is_final?: boolean;
  rejected?: boolean;
  client_uid?: string;
  history_uid?: string;
  utterance_filter?: {
    enabled?: boolean;
    min_rms_dbfs?: number;
    min_peak_dbfs?: number;
  };
}

export interface ChatLine {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  time: string;
}

export interface LiveTalkingConfig {
  serviceUrl: string;
  avatarId: string;
  useStun: boolean;
}

export interface OfferResponse {
  sdp?: string;
  type?: RTCSdpType;
  sessionid?: string;
  code?: number;
  msg?: string;
}
