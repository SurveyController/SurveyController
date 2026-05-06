import { extractUserIdFromMessage, normalizeMessageType } from "./message.js";
import { jsonResponse } from "./response.js";

export async function parseIncomingRequest(request) {
  const contentType = request.headers.get("Content-Type") || "";
  let message = "";
  let userId = "";
  let messageType = "";
  let issueTitle = "";
  let timestamp = "";
  const files = [];

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
      if (value instanceof File) {
        files.push(value);
      }
    }

    return { message, files, userId, messageType, issueTitle, timestamp };
  }

  if (contentType.includes("application/json")) {
    const body = await request.json();
    if (typeof body?.message === "string") {
      message = body.message;
    }
    if (typeof body?.userId === "string") {
      userId = body.userId.trim();
    } else if (typeof body?.user_id === "string") {
      userId = body.user_id.trim();
    }
    if (typeof body?.messageType === "string") {
      messageType = body.messageType.trim();
    } else if (typeof body?.message_type === "string") {
      messageType = body.message_type.trim();
    }
    if (typeof body?.issueTitle === "string") {
      issueTitle = body.issueTitle.trim();
    } else if (typeof body?.issue_title === "string") {
      issueTitle = body.issue_title.trim();
    }
    if (typeof body?.timestamp === "string") {
      timestamp = body.timestamp.trim();
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

export function validatePayload(message, files) {
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

export async function parseTelegramUpdate(request) {
  const contentType = request.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }

  try {
    const body = await request.clone().json();
    if (body?.callback_query) {
      return body;
    }
  } catch {
    return null;
  }

  return null;
}
