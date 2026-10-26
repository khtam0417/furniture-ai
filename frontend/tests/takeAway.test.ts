// Run: npm --prefix frontend test
import { test } from "node:test";
import assert from "node:assert/strict";
import { exportUrls } from "../src/design/takeAway.ts";

test("downloads are tied to the current design version", () => {
  assert.deepEqual(exportUrls("apt_1", 12), {
    html: "/api/apartments/apt_1/design/export.html?version=12",
    xlsx: "/api/apartments/apt_1/design/export.xlsx?version=12",
  });
  assert.equal(exportUrls("a/../b", 3).html, "/api/apartments/a%2F..%2Fb/design/export.html?version=3");  // ids can't change the path
});
