export const RELEASES_URL = "https://github.com/Yi-luo-hua/BilibiliCrawler/releases";
export const RELEASE_API = "https://api.github.com/repos/Yi-luo-hua/BilibiliCrawler/releases/latest";

/** A failure this module authored, and therefore the only kind safe to show.
 *
 * Everything else reaching the caller was written by the network stack or the
 * JSON parser. A `SyntaxError` from a malformed body can quote the body itself,
 * so those are reported as a fixed line instead of being printed. */
export class UpdateCheckError extends Error {}

/** The line to show the user for a failed check. Pure, so it can be tested
 * without a component: the rule is what matters, not where it is rendered. */
export function checkFailureMessage(error: unknown, aborted: boolean): string {
  if (aborted) return "检查超时或已取消，请重试。";
  if (error instanceof UpdateCheckError) return `无法检查更新：${error.message}`;
  return "无法检查更新，请检查网络后重试。";
}

export interface DesktopRelease {
  version: string;
  notes: string;
  url: string;
  downloadUrl: string | null;
}

function versionParts(version: string): number[] {
  if (!/^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version)) {
    throw new UpdateCheckError("无法识别版本号，请到发布页面检查更新。");
  }
  const parts = version.replace(/^v/, "").split(".").map(Number);
  if (!parts.every(Number.isSafeInteger)) throw new UpdateCheckError("版本号超出有效范围。");
  return parts;
}

export function isNewerVersion(latest: string, current: string): boolean {
  const left = versionParts(latest);
  const right = versionParts(current);
  for (let i = 0; i < 3; i++) {
    if (left[i] !== right[i]) return left[i] > right[i];
  }
  return false;
}

export function parseRelease(value: unknown): DesktopRelease {
  if (!value || typeof value !== "object") throw new UpdateCheckError("发布信息格式无效。");
  const release = value as Record<string, unknown>;
  if (release.draft !== false || release.prerelease !== false || typeof release.tag_name !== "string") {
    throw new UpdateCheckError("未找到可用的正式版本。");
  }
  versionParts(release.tag_name);
  const version = release.tag_name.replace(/^v/, "");
  const url = `${RELEASES_URL}/tag/${release.tag_name}`;
  const name = `BilibiliCrawler-Setup-${version}-x64.exe`;
  const expectedUrl = `${RELEASES_URL}/download/${release.tag_name}/${name}`;
  const assets = Array.isArray(release.assets) ? release.assets : [];
  const available = assets.some((asset) => asset && asset.name === name &&
    asset.state === "uploaded" && asset.size > 0 && asset.browser_download_url === expectedUrl);
  return { version, url, notes: typeof release.body === "string" ? release.body : "暂无更新说明。",
    downloadUrl: available ? expectedUrl : null };
}

export async function checkForUpdate(signal?: AbortSignal): Promise<DesktopRelease> {
  const response = await fetch(RELEASE_API, {
    headers: { Accept: "application/vnd.github+json" },
    signal: signal ?? AbortSignal.timeout(15000),
    cache: "no-store",
  });
  if (!response.ok) {
    if (response.status === 403 || response.status === 429) throw new UpdateCheckError("检查过于频繁或访问受限，请稍后重试。");
    if (response.status === 404) throw new UpdateCheckError("尚无公开的正式版本。");
    throw new UpdateCheckError(`检查更新失败（HTTP ${response.status}）。`);
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    // Not re-thrown: the parser's message can carry a slice of the body.
    throw new UpdateCheckError("发布信息无法解析，请到发布页面检查更新。");
  }
  return parseRelease(payload);
}
