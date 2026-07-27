const MAX_UID = 10 ** 12;
const SPACE_URL_PATTERN =
  /^(?:https?:\/\/)?space\.bilibili\.com\/(\d+)(?:[/?#].*)?$/i;

export function parseDynamicTarget(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) return null;

  const match = trimmed.match(SPACE_URL_PATTERN);
  const rawUid = match?.[1] ?? (/^\d+$/.test(trimmed) ? trimmed : "");
  const uid = Number(rawUid);

  if (!rawUid || !Number.isSafeInteger(uid) || uid <= 0 || uid >= MAX_UID) {
    throw new Error("请输入有效的用户 UID 或 B 站空间主页链接");
  }

  return uid;
}
