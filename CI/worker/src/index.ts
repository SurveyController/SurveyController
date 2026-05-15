import { CORS_HEADERS, TELEGRAM_WEBHOOK_PATH } from "./constants";
import { createGitHubIssue } from "./github";
import { parseIncomingRequest, parseTelegramUpdate, validatePayload } from "./request";
import { jsonResponse } from "./response";
import {
  buildTaskReplyMarkup,
  handleCallbackQuery,
  sendHomogeneousFiles,
  sendMessage,
  splitFilesByType,
  verifyTelegramWebhookSecret,
} from "./telegram";
import type { ContactPayload, Env } from "./types";

function buildTelegramApiBase(botToken: string): string {
  return `https://api.telegram.org/bot${botToken}`;
}

function readEnvValue(value: string | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

function onlyPostResponse(): Response {
  return new Response("Only POST allowed", { status: 405, headers: CORS_HEADERS });
}

async function handleTelegramWebhookRequest(env: Env, request: Request): Promise<Response> {
  if (!verifyTelegramWebhookSecret(request, env)) {
    return jsonResponse({ error: "invalid_telegram_webhook_secret" }, 403);
  }

  const botToken = readEnvValue(env.BOT_TOKEN);
  if (!botToken) {
    return jsonResponse({ error: "missing_required_secrets" }, 500);
  }

  const telegramUpdate = await parseTelegramUpdate(request);
  if (!telegramUpdate?.callback_query) {
    return jsonResponse({ error: "unsupported_telegram_update" }, 400);
  }

  return handleCallbackQuery(buildTelegramApiBase(botToken), telegramUpdate.callback_query);
}

async function deliverContactToTelegram(
  apiBase: string,
  chatId: string,
  payload: ContactPayload,
): Promise<void> {
  const { message, files, userId } = payload;
  const taskReplyMarkup = userId ? buildTaskReplyMarkup(userId) : null;
  const { images, documents } = splitFilesByType(files);

  if (files.length === 0) {
    await sendMessage(apiBase, chatId, message, taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {});
    return;
  }

  if (images.length > 0 && documents.length > 0) {
    if (message) {
      await sendMessage(apiBase, chatId, message, taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {});
    } else if (taskReplyMarkup) {
      await sendMessage(apiBase, chatId, `待处理工单\n工单用户ID：${userId}`, {
        reply_markup: taskReplyMarkup,
      });
    }
    await sendHomogeneousFiles(apiBase, chatId, images);
    await sendHomogeneousFiles(apiBase, chatId, documents);
    return;
  }

  if (files.length === 1) {
    await sendHomogeneousFiles(
      apiBase,
      chatId,
      files,
      message || undefined,
      taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {},
    );
    return;
  }

  if (message) {
    await sendMessage(apiBase, chatId, message, taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {});
  } else if (taskReplyMarkup) {
    await sendMessage(apiBase, chatId, `待处理工单\n工单用户ID：${userId}`, {
      reply_markup: taskReplyMarkup,
    });
  }
  await sendHomogeneousFiles(apiBase, chatId, files);
}

async function handleContactRequest(env: Env, request: Request): Promise<Response> {
  const botToken = readEnvValue(env.BOT_TOKEN);
  const chatId = readEnvValue(env.CHAT_ID);
  if (!botToken || !chatId) {
    return jsonResponse({ error: "missing_required_secrets" }, 500);
  }

  const payload = await parseIncomingRequest(request);
  const validation = validatePayload(payload.message, payload.files);
  if (!validation.ok) {
    return validation.response;
  }

  const apiBase = buildTelegramApiBase(botToken);
  await deliverContactToTelegram(apiBase, chatId, payload);

  let githubIssue = null;
  let githubIssueError = "";
  if (payload.messageType === "报错反馈") {
    try {
      githubIssue = await createGitHubIssue(env, payload);
    } catch (error) {
      githubIssueError = error instanceof Error ? error.message : "github_issue_create_failed";
    }
  }

  return jsonResponse({
    status: "ok",
    githubIssue,
    githubIssueError,
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const { pathname } = new URL(request.url);

    try {
      if (pathname === TELEGRAM_WEBHOOK_PATH) {
        if (request.method !== "POST") {
          return onlyPostResponse();
        }
        return await handleTelegramWebhookRequest(env, request);
      }

      if (pathname !== "/") {
        return new Response("Not found", { status: 404, headers: CORS_HEADERS });
      }

      if (request.method !== "POST") {
        return onlyPostResponse();
      }

      return await handleContactRequest(env, request);
    } catch (error) {
      const message = error instanceof Error ? error.message : "internal_error";
      return jsonResponse({ error: message }, 500);
    }
  },
} satisfies ExportedHandler<Env>;
