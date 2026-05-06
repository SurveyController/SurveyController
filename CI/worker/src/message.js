export function extractUserIdFromMessage(message) {
  if (typeof message !== "string") {
    return "";
  }
  const match = message.match(/随机IP用户ID：\s*(\d+)/);
  return match ? match[1] : "";
}

export function extractMessageLineValue(message, prefix) {
  if (typeof message !== "string" || !prefix) {
    return "";
  }
  const lines = message.split(/\r?\n/);
  for (const line of lines) {
    if (line.startsWith(prefix)) {
      return line.slice(prefix.length).trim();
    }
  }
  return "";
}

export function normalizeMessageType(rawType, message) {
  const directType = typeof rawType === "string" ? rawType.trim() : "";
  if (directType) {
    return directType;
  }
  return extractMessageLineValue(message, "类型：");
}

export function extractVersionFromMessage(message) {
  return (
    extractMessageLineValue(message, "来源：SurveyController v") ||
    extractMessageLineValue(message, "版本号：SurveyController v")
  );
}

function stripEmailLine(message) {
  if (typeof message !== "string" || !message) {
    return "";
  }
  return message
    .split(/\r?\n/)
    .filter((line) => !line.startsWith("联系邮箱："))
    .join("\n")
    .trim();
}

export function sanitizeIssueTitle(title) {
  if (typeof title !== "string") {
    return "";
  }
  return title.replace(/\s+/g, " ").trim().slice(0, 60);
}

export function extractIssueTitleFromMessage(message) {
  return extractMessageLineValue(message, "反馈标题：");
}

export function extractIssueMessageContent(message) {
  if (typeof message !== "string" || !message.trim()) {
    return "";
  }

  const sanitizedMessage = stripEmailLine(message);
  const match = sanitizedMessage.match(/(?:^|\n)消息：([\s\S]*)$/);
  if (match) {
    return match[1].trim();
  }

  return sanitizedMessage.trim();
}
