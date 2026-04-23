type CopyPayload = {
  text: string;
  html?: string;
};

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function copyWithExecCommand(payload: CopyPayload): void {
  if (typeof document === "undefined") {
    throw new Error("Clipboard API is unavailable");
  }

  const div = document.createElement("div");
  div.contentEditable = "true";
  div.style.position = "fixed";
  div.style.top = "0";
  div.style.left = "0";
  div.style.opacity = "0";
  div.style.pointerEvents = "none";
  div.innerHTML = payload.html ?? escapeHtml(payload.text).replaceAll("\n", "<br>");
  document.body.appendChild(div);

  const range = document.createRange();
  range.selectNodeContents(div);

  const selection = window.getSelection();
  if (!selection) {
    document.body.removeChild(div);
    throw new Error("Selection API is unavailable");
  }

  selection.removeAllRanges();
  selection.addRange(range);

  try {
    const copied = document.execCommand("copy");
    if (!copied) {
      throw new Error("Copy command failed");
    }
  } finally {
    selection.removeAllRanges();
    document.body.removeChild(div);
  }
}

export async function copyClipboard(payload: CopyPayload): Promise<void> {
  copyWithExecCommand(payload);
}

export async function copyText(value: string): Promise<void> {
  await copyClipboard({ text: value });
}

export { escapeHtml };
