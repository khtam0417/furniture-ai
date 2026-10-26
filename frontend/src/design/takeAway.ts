// "Take your checklist with you": download links (pure; unit-tested).

/** Download addresses for the CURRENT design version (the server refuses an older version). */
export function exportUrls(aid: string, version: number): { html: string; xlsx: string } {
  const a = encodeURIComponent(aid);
  return {
    html: `/api/apartments/${a}/design/export.html?version=${version}`,
    xlsx: `/api/apartments/${a}/design/export.xlsx?version=${version}`,
  };
}
