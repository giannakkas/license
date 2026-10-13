"use client";

import { useEffect } from "react";

/** Starts a file download as soon as the page shows (used right after an offline file is issued). */
export function AutoDownload({ url }: { url: string }) {
  useEffect(() => {
    window.location.assign(url);
  }, [url]);
  return null;
}
