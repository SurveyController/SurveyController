import { extractUserIdFromMessage, normalizeMessageType } from "./message";
import { jsonResponse } from "./response";
import type { ContactPayload, TelegramUpdate, ValidationResult } from "./types";

function readStringRecordValue(source: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string") {
      return value.trim();
    }
  }
  return "";
}

function isRequestFile(value: unknown): value is File {
  if (!value || typeof value !== "object") {
    return false;
  }
  return typeof (value as File).arrayBuffer === "function" && typeof (value as File).name === "string";
}

export async function parseIncomingRequest(request: Request): Promise<ContactPayload> {
  const contentType = request.headers.get("Content-Type") || "";
  let message = "";
  let userId = "";
  let messageType = "";
  let issueTitle = "";
  let timestamp = "";
  const files: File[] = [];

  if (contentType.includes("multipart/form-data") || contentType.includes("form-data")) {
    const form = await request.formData();
    const maybeMessage = form.get("message");
    if (typeof maybeMessage === "string") {
      message = maybeMessage;
    }

    const maybeUserId = form.get("userId") ?? form.get("user_id");
    if (typeof maybeUserId === "string") {
      userId = maybeUserId.trim();
    }

    const maybeMessageType = form.get("messageType") ?? form.get("message_type");
    if (typeof maybeMessageType === "string") {
      messageType = maybeMessageType.trim();
    }

    const maybeIssueTitle = form.get("issueTitle") ?? form.get("issue_title");
    if (typeof maybeIssueTitle === "string") {
      issueTitle = maybeIssueTitle.trim();
    }

    const maybeTimestamp = form.get("timestamp");
    if (typeof maybeTimestamp === "string") {
      timestamp = maybeTimestamp.trim();
    }

    if (!userId) {
      userId = extractUserIdFromMessage(message);
    }
    messageType = normalizeMessageType(messageType, message);

    for (const [, value] of form.entries()) {
      if (isRequestFile(value)) {
        files.push(value);
      }
    }

    return { message, files, userId, messageType, issueTitle, timestamp };
  }

  if (contentType.includes("application/json")) {
    const body = await request.json();
    if (body && typeof body === "object") {
      const record = body as Record<string, unknown>;
      const maybeMessage = record.message;
      if (typeof maybeMessage === "string") {
        message = maybeMessage;
      }
      userId = readStringRecordValue(record, "userId", "user_id");
      messageType = readStringRecordValue(record, "messageType", "message_type");
      issueTitle = readStringRecordValue(record, "issueTitle", "issue_title");
      timestamp = readStringRecordValue(record, "timestamp");
    }

    if (!userId) {
      userId = extractUserIdFromMessage(message);
    }
    messageType = normalizeMessageType(messageType, message);

    return { message, files, userId, messageType, issueTitle, timestamp };
  }

  const text = await request.text();
  if (text) {
    message = text;
  }
  userId = extractUserIdFromMessage(message);
  messageType = normalizeMessageType(messageType, message);
  return { message, files, userId, messageType, issueTitle, timestamp };
}

export function validatePayload(message: string, files: File[]): ValidationResult {
  const maxFiles = 6;
  const maxFileSize = 10 * 1024 * 1024;

  if (files.length > maxFiles) {
    return { ok: false, response: jsonResponse({ error: `too_many_files_max_${maxFiles}` }, 400) };
  }

  for (const file of files) {
    if (file.size > maxFileSize) {
      return { ok: false, response: jsonResponse({ error: "file_too_large_max_10mb" }, 400) };
    }
  }

  if (!message && files.length === 0) {
    return { ok: false, response: jsonResponse({ error: "no_message_or_files" }, 400) };
  }

  return { ok: true };
}

export async function parseTelegramUpdate(request: Request): Promise<TelegramUpdate | null> {
  const contentType = request.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }

  try {
    const body = await request.json();
    if (!body || typeof body !== "object") {
      return null;
    }
    const update = body as TelegramUpdate;
    return update.callback_query ? update : null;
  } catch {
    return null;
  }
}
