export const CORS_HEADERS: Readonly<Record<string, string>> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Telegram-Bot-Api-Secret-Token",
};

export const JSON_HEADERS: Readonly<Record<string, string>> = {
  "Content-Type": "application/json",
  "Access-Control-Allow-Origin": "*",
};

export const DEFAULT_GITHUB_OWNER = "SurveyController";
export const DEFAULT_GITHUB_REPO = "SurveyController";
export const GITHUB_API_VERSION = "2022-11-28";
export const TELEGRAM_FETCH_TIMEOUT_MS = 8000;
export const GITHUB_FETCH_TIMEOUT_MS = 8000;
export const TELEGRAM_WEBHOOK_PATH = "/telegram/webhook";
