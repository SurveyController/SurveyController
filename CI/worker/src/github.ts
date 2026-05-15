import {
  DEFAULT_GITHUB_OWNER,
  DEFAULT_GITHUB_REPO,
  GITHUB_API_VERSION,
  GITHUB_FETCH_TIMEOUT_MS,
} from "./constants";
import {
  extractIssueMessageContent,
  extractIssueTitleFromMessage,
  extractVersionFromMessage,
  sanitizeIssueTitle,
} from "./message";
import type { ContactPayload, Env, GitHubIssueResult } from "./types";

const DEFAULT_GITHUB_ISSUE_LABELS = ["bot"];

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs = GITHUB_FETCH_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort("github_timeout"), timeoutMs);
  try {
    return await fetch(url, {
      ...init,
      signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("github_request_timeout");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function safeJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function isGitHubLogFile(file: File): boolean {
  const fileName = typeof file.name === "string" ? file.name.toLowerCase() : "";
  return fileName === "fatal_crash.log" || (fileName.startsWith("bug_report_log_") && fileName.endsWith(".txt"));
}

async function buildGitHubLogSections(files: File[]): Promise<string[]> {
  if (files.length === 0) {
    return [];
  }

  const sections: string[] = [];
  for (const file of files) {
    if (!isGitHubLogFile(file)) {
      continue;
    }

    let text = "";
    try {
      text = await file.text();
    } catch {
      text = "";
    }

    const trimmedText = text.trim();
    if (!trimmedText) {
      continue;
    }

    const truncated = trimmedText.length > 20000;
    const displayText = truncated ? `${trimmedText.slice(0, 20000)}\n\n[日志内容过长，已截断]` : trimmedText;
    sections.push(
      [
        "<details>",
        `<summary>报错日志：${escapeHtml(file.name || "未命名日志")}</summary>`,
        "",
        "<pre><code>",
        escapeHtml(displayText),
        "</code></pre>",
        "</details>",
      ].join("\n"),
    );
  }

  return sections;
}

function buildGitHubIssueTitle({ issueTitle, message }: Pick<ContactPayload, "issueTitle" | "message">): string {
  const explicitTitle = sanitizeIssueTitle(issueTitle);
  if (explicitTitle) {
    return explicitTitle;
  }

  const extractedTitle = sanitizeIssueTitle(extractIssueTitleFromMessage(message));
  if (extractedTitle) {
    return extractedTitle;
  }

  const messageTitle = sanitizeIssueTitle(extractIssueMessageContent(message));
  if (messageTitle) {
    return messageTitle;
  }

  return "报错反馈";
}

async function buildGitHubIssueBody({ message, files }: Pick<ContactPayload, "message" | "files">): Promise<string> {
  const version = extractVersionFromMessage(message);
  const issueMessage = extractIssueMessageContent(message);
  const logSections = await buildGitHubLogSections(files);

  const lines: string[] = [];
  if (version) {
    lines.push(`版本号：SurveyController v${version}`);
  }
  if (issueMessage) {
    lines.push(issueMessage);
  } else {
    lines.push("未提供正文");
  }
  if (logSections.length > 0) {
    lines.push("", ...logSections);
  }

  return lines.join("\n");
}

function parseConfiguredIssueLabels(env: Env): string[] {
  const raw = typeof env.GITHUB_ISSUE_LABELS === "string" ? env.GITHUB_ISSUE_LABELS : "";
  const configuredLabels = raw
    .split(",")
    .map((label) => label.trim())
    .filter(Boolean);

  return configuredLabels.length > 0 ? configuredLabels : DEFAULT_GITHUB_ISSUE_LABELS;
}

async function fetchExistingGitHubLabels(args: { owner: string; repo: string; token: string }): Promise<Set<string>> {
  const response = await fetchWithTimeout(`https://api.github.com/repos/${args.owner}/${args.repo}/labels?per_page=100`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${args.token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "SurveyController-Worker",
      "X-GitHub-Api-Version": GITHUB_API_VERSION,
    },
  });

  if (!response.ok) {
    return new Set();
  }

  const result = await safeJson(response);
  if (!Array.isArray(result)) {
    return new Set();
  }

  return new Set(
    result
      .map((label) => {
        if (!label || typeof label !== "object") {
          return "";
        }
        const name = (label as { name?: unknown }).name;
        return typeof name === "string" ? name.trim() : "";
      })
      .filter(Boolean),
  );
}

export async function createGitHubIssue(
  env: Env,
  payload: Pick<ContactPayload, "issueTitle" | "message" | "files">,
): Promise<GitHubIssueResult | null> {
  const token = typeof env.GITHUB_TOKEN === "string" ? env.GITHUB_TOKEN.trim() : "";
  if (!token) {
    return null;
  }

  const owner = env.GITHUB_OWNER || DEFAULT_GITHUB_OWNER;
  const repo = env.GITHUB_REPO || DEFAULT_GITHUB_REPO;
  const existingLabels = await fetchExistingGitHubLabels({ owner, repo, token });
  const labels = parseConfiguredIssueLabels(env).filter((label) => existingLabels.has(label));

  const response = await fetchWithTimeout(`https://api.github.com/repos/${owner}/${repo}/issues`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "SurveyController-Worker",
      "X-GitHub-Api-Version": GITHUB_API_VERSION,
    },
    body: JSON.stringify({
      title: buildGitHubIssueTitle(payload),
      body: await buildGitHubIssueBody(payload),
      ...(labels.length > 0 ? { labels } : {}),
    }),
  });

  const result = await safeJson(response);
  const record = result && typeof result === "object" ? (result as Record<string, unknown>) : {};

  if (!response.ok) {
    const message =
      typeof record.message === "string" && record.message.trim()
        ? record.message
        : `github_issue_create_failed_${response.status}`;
    throw new Error(message);
  }

  return {
    number: typeof record.number === "number" ? record.number : 0,
    url: typeof record.html_url === "string" ? record.html_url : "",
  };
}
