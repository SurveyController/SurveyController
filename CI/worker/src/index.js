import { CORS_HEADERS } from "./constants.js";
import { createGitHubIssue } from "./github.js";
import { parseIncomingRequest, parseTelegramUpdate, validatePayload } from "./request.js";
import { jsonResponse } from "./response.js";
import {
  buildTaskReplyMarkup,
  ensureTelegramWebhook,
  handleCallbackQuery,
  sendHomogeneousFiles,
  sendMessage,
  splitFilesByType,
} from "./telegram.js";

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    if (request.method !== "POST") {
      return new Response("Only POST allowed", { status: 405, headers: CORS_HEADERS });
    }

    const botToken = env.BOT_TOKEN;
    const chatId = env.CHAT_ID;
    if (!botToken || !chatId) {
      return jsonResponse({ error: "missing_required_secrets" }, 500);
    }

    try {
      const apiBase = `https://api.telegram.org/bot${botToken}`;
      const telegramUpdate = await parseTelegramUpdate(request);
      if (telegramUpdate?.callback_query) {
        return handleCallbackQuery(apiBase, telegramUpdate.callback_query);
      }

      const { message, files, userId, messageType, issueTitle, timestamp } = await parseIncomingRequest(request);
      const validation = validatePayload(message, files);
      if (!validation.ok) {
        return validation.response;
      }

      const taskReplyMarkup = userId ? buildTaskReplyMarkup(userId) : null;
      const shouldCreateGitHubIssue = messageType === "报错反馈";
      if (userId) {
        await ensureTelegramWebhook(apiBase, request.url);
      }

      const { images, documents } = splitFilesByType(files);
      let githubIssue = null;
      let githubIssueError = "";

      if (files.length === 0) {
        await sendMessage(apiBase, chatId, message, taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {});
      } else if (images.length > 0 && documents.length > 0) {
        if (message) {
          await sendMessage(apiBase, chatId, message, taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {});
        } else if (taskReplyMarkup) {
          await sendMessage(apiBase, chatId, `待处理工单\n工单用户ID：${userId}`, {
            reply_markup: taskReplyMarkup,
          });
        }
        await sendHomogeneousFiles(apiBase, chatId, images);
        await sendHomogeneousFiles(apiBase, chatId, documents);
      } else if (files.length === 1) {
        await sendHomogeneousFiles(
          apiBase,
          chatId,
          files,
          message || undefined,
          taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {},
        );
      } else {
        if (message) {
          await sendMessage(apiBase, chatId, message, taskReplyMarkup ? { reply_markup: taskReplyMarkup } : {});
        } else if (taskReplyMarkup) {
          await sendMessage(apiBase, chatId, `待处理工单\n工单用户ID：${userId}`, {
            reply_markup: taskReplyMarkup,
          });
        }
        await sendHomogeneousFiles(apiBase, chatId, files);
      }

      if (shouldCreateGitHubIssue) {
        try {
          githubIssue = await createGitHubIssue(env, {
            issueTitle,
            message,
            userId,
            timestamp,
            files,
          });
        } catch (error) {
          githubIssueError = error instanceof Error ? error.message : "github_issue_create_failed";
        }
      }

      return jsonResponse({
        status: "ok",
        githubIssue,
        githubIssueError,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "internal_error";
      return jsonResponse({ error: message }, 500);
    }
  },
};
