export interface Env {
  BOT_TOKEN?: string;
  CHAT_ID?: string;
  TELEGRAM_WEBHOOK_SECRET?: string;
  GITHUB_TOKEN?: string;
  GITHUB_OWNER?: string;
  GITHUB_REPO?: string;
  GITHUB_ISSUE_LABELS?: string;
}

export interface ContactPayload {
  message: string;
  files: File[];
  userId: string;
  messageType: string;
  issueTitle: string;
  timestamp: string;
}

export type ValidationResult = { ok: true } | { ok: false; response: Response };

export interface GitHubIssueResult {
  number: number;
  url: string;
}

export interface TelegramUser {
  id?: number | string;
  first_name?: string;
  last_name?: string;
  username?: string;
}

export interface TelegramChat {
  id?: number | string;
}

export interface TelegramMessage {
  chat?: TelegramChat;
}

export interface TelegramCallbackQuery {
  id?: string;
  data?: string;
  message?: TelegramMessage;
  from?: TelegramUser;
}

export interface TelegramUpdate {
  callback_query?: TelegramCallbackQuery;
}
