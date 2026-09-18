window.CONTRACK_CONFIG = {
  apiBase: "/api",
  nodeServerBase: "http://127.0.0.1:3219",
  openXmlBase: `http://${window.location.hostname || "127.0.0.1"}:5000`,
  // Optional override; by default use VITE_FILEHANDLER_BASE or this web host on port 5001.
  // fileHandlerBase: "http://translation-server:5001",
};
