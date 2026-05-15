import { jsonResponse } from "./response";
import { TELEGRAM_FETCH_TIMEOUT_MS } from "./constants";
import type { Env, TelegramCallbackQuery, TelegramUser } from "./types";

type ReplyMarkup = Record<string, unknown>;
type TelegramChatId = string | number;

async function sendTelegramRequest<T>(apiBase: string, endpoint: string, init: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort("telegram_timeout"), TELEGRAM_FETCH_TIMEOUT_MS);
  let response: Response;

  try {
    response = await fetch(`${apiBase}/${endpoint}`, {
      ...init,
      signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("telegram_request_timeout");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const record = payload && typeof payload === "object" ? (payload as Record<string, unknown>) : {};
  const ok = record.ok === true;

  if (!response.ok || !ok) {
    const description =
      typeof record.description === "string" && record.description.trim()
        ? record.description
        : `telegram_request_failed_${response.status}`;
    throw new Error(description);
  }

  return record.result as T;
}

export async function sendMessage(
  apiBase: string,
  chatId: TelegramChatId,
  text: string,
  options: Record<string, unknown> = {},
): Promise<unknown> {
  return sendTelegramRequest(apiBase, "sendMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chatId,
      text,
      ...options,
    }),
  });
}

async function sendSingleFile(
  apiBase: string,
  chatId: TelegramChatId,
  file: File,
  caption?: string,
  options: { reply_markup?: ReplyMarkup } = {},
): Promise<unknown> {
  const isImage = file.type.startsWith("image/");
  const form = new FormData();
  form.append("chat_id", String(chatId));
  form.append(isImage ? "photo" : "document", file, file.name || "upload");
  if (caption) {
    form.append("caption", caption);
  }
  if (options.reply_markup) {
    form.append("reply_markup", JSON.stringify(options.reply_markup));
  }

  return sendTelegramRequest(apiBase, isImage ? "sendPhoto" : "sendDocument", {
    method: "POST",
    body: form,
  });
}

export function splitFilesByType(fileList: File[]): { images: File[]; documents: File[] } {
  const images: File[] = [];
  const documents: File[] = [];

  for (const file of fileList) {
    if (file.type.startsWith("image/")) {
      images.push(file);
    } else {
      documents.push(file);
    }
  }

  return { images, documents };
}

async function sendMediaGroup(
  apiBase: string,
  chatId: TelegramChatId,
  fileList: File[],
  caption?: string,
): Promise<unknown> {
  const form = new FormData();
  form.append("chat_id", String(chatId));

  const media = fileList.map((file, index) => {
    const name = `file${index + 1}`;
    const isImage = file.type.startsWith("image/");
    form.append(name, file, file.name || name);

    const item: Record<string, unknown> = {
      type: isImage ? "photo" : "document",
      media: `attach://${name}`,
    };

    if (index === 0 && caption) {
      item.caption = caption;
    }

    return item;
  });

  form.append("media", JSON.stringify(media));
  return sendTelegramRequest(apiBase, "sendMediaGroup", {
    method: "POST",
    body: form,
  });
}

export async function sendHomogeneousFiles(
  apiBase: string,
  chatId: TelegramChatId,
  fileList: File[],
  caption?: string,
  options: { reply_markup?: ReplyMarkup } = {},
): Promise<unknown> {
  if (!fileList.length) {
    return null;
  }
  if (fileList.length === 1) {
    return sendSingleFile(apiBase, chatId, fileList[0], caption, options);
  }
  return sendMediaGroup(apiBase, chatId, fileList, caption);
}

function buildTaskCallbackData(userId: string): string {
  return `done:${userId}`;
}

export function buildTaskReplyMarkup(userId: string): ReplyMarkup {
  return {
    inline_keyboard: [[{ text: "点击标记为已处理", callback_data: buildTaskCallbackData(userId) }]],
  };
}

export function verifyTelegramWebhookSecret(request: Request, env: Env): boolean {
  const expected = typeof env.TELEGRAM_WEBHOOK_SECRET === "string" ? env.TELEGRAM_WEBHOOK_SECRET.trim() : "";
  if (!expected) {
    return true;
  }
  return request.headers.get("X-Telegram-Bot-Api-Secret-Token") === expected;
}

function escapeMarkdownV2(value: string): string {
  return value.replace(/([_*\[\]()~`>#+\-=|{}.!\\])/g, "\\$1");
}

function parseTaskCallbackData(data: string | undefined): { userId: string } | null {
  if (!data || !data.startsWith("done:")) {
    return null;
  }

  const userId = data.slice(5).trim();
  if (!userId) {
    return null;
  }

  return { userId };
}

async function answerCallbackQuery(apiBase: string, callbackQueryId: string, text: string): Promise<void> {
  await sendTelegramRequest(apiBase, "answerCallbackQuery", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      callback_query_id: callbackQueryId,
      text,
    }),
  });
}

function getActorDisplayName(from: TelegramUser | undefined): string {
  if (!from) {
    return "未知用户";
  }

  const fullName = [from.first_name, from.last_name].filter(Boolean).join(" ").trim();
  if (fullName) {
    return fullName;
  }
  if (typeof from.username === "string" && from.username.trim()) {
    return from.username.trim();
  }
  return String(from.id || "未知用户");
}

export async function handleCallbackQuery(apiBase: string, callbackQuery: TelegramCallbackQuery): Promise<Response> {
  const parsed = parseTaskCallbackData(callbackQuery.data);
  if (!parsed) {
    return jsonResponse({ error: "unsupported_callback_query" }, 400);
  }

  const callbackQueryId = callbackQuery.id;
  const chatId = callbackQuery.message?.chat?.id;
  const actorId = callbackQuery.from?.id;
  if (!callbackQueryId || chatId === undefined || actorId === undefined) {
    return jsonResponse({ error: "invalid_callback_query_payload" }, 400);
  }

  await answerCallbackQuery(apiBase, callbackQueryId, "已记录处理结果");

  const actorName = escapeMarkdownV2(getActorDisplayName(callbackQuery.from));
  const actorMention = `[${actorName}](tg://user?id=${actorId})`;
  const escapedUserId = escapeMarkdownV2(parsed.userId);
  await sendMessage(
    apiBase,
    chatId,
    `该工单已处理\n处理人：${actorMention}\n工单用户ID：${escapedUserId}`,
    {
      parse_mode: "MarkdownV2",
    },
  );

  return jsonResponse({ status: "ok" });
}
