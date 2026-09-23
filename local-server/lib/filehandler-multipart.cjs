// Parse MIME framing as bytes so Office ZIP payloads and original newlines survive unchanged.
function parseMultipart(bytes, contentType) {
  const match = /(?:^|;)\s*boundary\s*=\s*(?:"([^"\r\n]+)"|([^;\s]+))/i.exec(contentType || "");
  if (!/^multipart\/mixed(?:\s*;|$)/i.test(contentType || "") || !match) {
    throw new Error("Expected multipart/mixed with a boundary from FileHandler");
  }
  const boundary = match[1] || match[2];
  const first = Buffer.from(`--${boundary}\r\n`);
  const delimiter = Buffer.from(`\r\n--${boundary}`);
  const matches = (marker, offset) => bytes.subarray(offset, offset + marker.length).equals(marker);
  const crlf = Buffer.from("\r\n");
  const closing = Buffer.from("--");
  const parts = [];
  if (!matches(first, 0)) throw new Error("Invalid FileHandler multipart opening boundary");
  let offset = first.length;
  while (offset < bytes.length) {
    const headerEnd = bytes.indexOf("\r\n\r\n", offset);
    if (headerEnd < 0) throw new Error("Incomplete FileHandler multipart headers");
    const headers = Object.create(null);
    for (const line of new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(offset, headerEnd)).split("\r\n")) {
      const colon = line.indexOf(":");
      if (colon < 1) throw new Error("Invalid FileHandler multipart header");
      const key = line.slice(0, colon).trim().toLowerCase();
      if (Object.hasOwn(headers, key)) throw new Error("Duplicate FileHandler multipart header");
      headers[key] = line.slice(colon + 1).trim();
    }
    const bodyStart = headerEnd + 4;
    let end = bytes.indexOf(delimiter, bodyStart);
    while (end >= 0) {
      const after = end + delimiter.length;
      if (matches(crlf, after) || (matches(closing, after)
          && (after + 2 === bytes.length || matches(crlf, after + 2)))) break;
      end = bytes.indexOf(delimiter, end + 1);
    }
    if (end < 0) throw new Error("Incomplete FileHandler multipart body");
    parts.push({ id: headers["content-id"], contentType: headers["content-type"] || "", bytes: bytes.subarray(bodyStart, end) });
    offset = end + delimiter.length;
    if (matches(closing, offset)) return parts;
    offset += 2;
  }
  throw new Error("Missing FileHandler multipart closing boundary");
}

module.exports = { parseMultipart };
