import { jsonResponse } from "./response.js";

async function sendTelegramRequest(apiBase, endpoint, init) {
  const response = await fetch(`${apiBase}/${endpoint}`, init);
  let payload = null;

  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok || !payload?.ok) {
    const description = payload?.description || `telegram_request_failed_${response.status}`;
    throw new Error(description);
  }

  return payload.result;
}

export async function sendMessage(apiBase, chatId, text, options = {}) {
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

async function sendSingleFile(apiBase, chatId, file, caption, options = {}) {
  const isImage = file.type && file.type.startsWith("image/");
  const form = new FormData();
  form.append("chat_id", chatId);
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

export function splitFilesByType(fileList) {
  const images = [];
  const documents = [];
  for (const file of fileList) {
    const isImage = file.type && file.type.startsWith("image/");
    if (isImage) {
      images.push(file);
    } else {
      documents.push(file);
    }
  }
  return { images, documents };
}

async function sendMediaGroup(apiBase, chatId, fileList, caption) {
  const form = new FormData();
  form.append("chat_id", chatId);

  const media = fileList.map((file, index) => {
    const name = `file${index + 1}`;
    const isImage = file.type && file.type.startsWith("image/");
    form.append(name, file, file.name || name);

    const item = {
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

export async function sendHomogeneousFiles(apiBase, chatId, fileList, caption, options = {}) {
  if (!fileList.length) {
    return;
  }
  if (fileList.length === 1) {
    return sendSingleFile(apiBase, chatId, fileList[0], caption, options);
  }
  return sendMediaGroup(apiBase, chatId, fileList, caption);
}

function buildTaskCallbackData(userId) {
  return `done:${userId}`;
}

export function buildTaskReplyMarkup(userId) {
  return {
    inline_keyboard: [[{ text: "点击标记为已处理", callback_data: buildTaskCallbackData(userId) }]],
  };
}

export async function ensureTelegramWebhook(apiBase, webhookUrl) {
  return sendTelegramRequest(apiBase, "setWebhook", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: webhookUrl,
      allowed_updates: ["callback_query"],
    }),
  });
}

function escapeMarkdownV2(value) {
  return String(value).replace(/([_*\[\]()~`>#+\-=|{}.!\\])/g, "\\$1");
}

function parseTaskCallbackData(data) {
  if (typeof data !== "string" || !data.startsWith("done:")) {
    return null;
  }

  const userId = data.slice(5).trim();
  if (!userId) {
    return null;
  }

  return { userId };
}

async function answerCallbackQuery(apiBase, callbackQueryId, text) {
  await sendTelegramRequest(apiBase, "answerCallbackQuery", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      callback_query_id: callbackQueryId,
      text,
    }),
  });
}

function getActorDisplayName(from) {
  if (!from || typeof from !== "object") {
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

export async function handleCallbackQuery(apiBase, callbackQuery) {
  const parsed = parseTaskCallbackData(callbackQuery?.data);
  if (!parsed) {
    return jsonResponse({ error: "unsupported_callback_query" }, 400);
  }

  const callbackQueryId = callbackQuery?.id;
  const chatId = callbackQuery?.message?.chat?.id;
  const actorId = callbackQuery?.from?.id;
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
