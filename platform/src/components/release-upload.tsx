"use client";

import { useState } from "react";

/** Uploads a build straight to the software's downloads with a progress bar. */
export function ReleaseUpload({ productId }: { productId: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [version, setVersion] = useState("");
  const [notes, setNotes] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");

  function upload() {
    if (!file || !version.trim()) {
      setError("Choose the file and type its version.");
      return;
    }
    setError("");
    setProgress(0);
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", `/api/admin/products/${productId}/releases`);
    xhr.setRequestHeader("content-type", "application/octet-stream");
    xhr.setRequestHeader("x-filename", encodeURIComponent(file.name));
    xhr.setRequestHeader("x-version", encodeURIComponent(version.trim()));
    xhr.setRequestHeader("x-notes", encodeURIComponent(notes.trim()));
    xhr.setRequestHeader("x-size", String(file.size));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status < 300) {
        window.location.reload();
        return;
      }
      setProgress(null);
      try {
        setError(JSON.parse(xhr.responseText).error ?? `Upload failed (${xhr.status})`);
      } catch {
        setError(`Upload failed (${xhr.status})`);
      }
    };
    xhr.onerror = () => {
      setProgress(null);
      setError("Upload failed: the connection dropped.");
    };
    xhr.send(file);
  }

  return (
    <div className="grid gap-3 md:grid-cols-[2fr_1fr_2fr_auto]">
      <label className="flex flex-col gap-1 text-sm">
        File (exe, zip or installer)
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} disabled={progress !== null} />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Version
        <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="1.3.0" disabled={progress !== null} />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Notes (optional)
        <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="What changed" disabled={progress !== null} />
      </label>
      <div className="flex items-end">
        <button type="button" className="btn btn-primary" onClick={upload} disabled={progress !== null}>
          {progress === null ? "Upload" : `${progress}%`}
        </button>
      </div>
      {progress !== null && (
        <div className="h-2 w-full overflow-hidden rounded bg-[#1e222b] md:col-span-4">
          <div className="h-full bg-[#3b82f6] transition-[width]" style={{ width: `${progress}%` }} />
        </div>
      )}
      {error && <p className="text-sm text-[#fca5a5] md:col-span-4">{error}</p>}
    </div>
  );
}
