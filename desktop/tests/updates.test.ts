import test from "node:test";
import assert from "node:assert/strict";
import { isNewerVersion, parseRelease, checkForUpdate, RELEASES_URL } from "../src/lib/updates.ts";

const release = () => ({ tag_name: "v3.10.0", draft: false, prerelease: false, body: "Changes", assets: [{
  name: "BilibiliCrawler-Setup-3.10.0-x64.exe", size: 100, state: "uploaded",
  browser_download_url: `${RELEASES_URL}/download/v3.10.0/BilibiliCrawler-Setup-3.10.0-x64.exe`,
}] });

test("compares numeric versions and never offers downgrades", () => {
  assert.equal(isNewerVersion("v3.10.0", "3.9.0"), true);
  assert.equal(isNewerVersion("3.5.0", "3.5.0"), false);
  assert.equal(isNewerVersion("3.5.0", "4.0.0"), false);
  for (const invalid of ["3.5", "3.5.1-beta", "03.5.1", "../x"]) {
    assert.throws(() => isNewerVersion(invalid, "3.5.0"));
  }
});

test("only offers uploaded installers from the expected repository and tag", () => {
  assert.ok(parseRelease(release()).downloadUrl);
  const foreign = release();
  foreign.assets[0].browser_download_url = "https://example.com/malware.exe";
  assert.equal(parseRelease(foreign).downloadUrl, null);
  assert.equal(parseRelease({ ...release(), assets: [] }).downloadUrl, null);
  assert.equal(parseRelease({ ...release(), assets: [null, {}] }).downloadUrl, null);
  // An asset that matches by name but is still being uploaded would hand the
  // user a broken download, so it must not produce a link either.
  const uploading = release();
  uploading.assets[0].state = "starter";
  assert.equal(parseRelease(uploading).downloadUrl, null);
  const empty = release();
  empty.assets[0].size = 0;
  assert.equal(parseRelease(empty).downloadUrl, null);
  assert.throws(() => parseRelease({ ...release(), prerelease: true }));
  assert.throws(() => parseRelease({ ...release(), draft: true }));
  assert.throws(() => parseRelease(null));
});

test("handles successful checks, rate limits and missing releases", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify(release())));
  assert.equal((await checkForUpdate()).version, "3.10.0");
  for (const status of [403, 404, 429, 500]) {
    t.mock.method(globalThis, "fetch", async () => new Response(null, { status }));
    await assert.rejects(checkForUpdate());
  }
});
