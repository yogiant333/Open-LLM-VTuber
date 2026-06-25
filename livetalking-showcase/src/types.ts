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
  text?: string;
  message?: string;
  success?: boolean;
  client_uid?: string;
  history_uid?: string;
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
