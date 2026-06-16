const DEFAULT_ALLOWED_HOSTS = ["tokenhub.tencentmaas.com"];

function getAllowedHosts() {
  return (process.env.LLM_PROXY_ALLOWED_HOSTS || DEFAULT_ALLOWED_HOSTS.join(","))
    .split(",")
    .map((host) => host.trim().toLowerCase())
    .filter(Boolean);
}

function parseTarget(req) {
  const requestUrl = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  const scheme = requestUrl.searchParams.get("scheme");
  const host = requestUrl.searchParams.get("host");
  const targetPath = requestUrl.searchParams.get("path") || "";

  if (scheme && host) {
    return buildTargetUrl(scheme, host, targetPath, requestUrl.search);
  }

  const match = requestUrl.pathname.match(/^\/api\/llm-proxy\/([^/]+)\/([^/]+)\/?(.*)$/);
  if (!match) {
    return null;
  }

  return buildTargetUrl(match[1], match[2], match[3] || "", "");
}

function buildTargetUrl(scheme, host, targetPath, search) {
  if (!["http", "https"].includes(scheme)) {
    return null;
  }

  const cleanHost = decodeURIComponent(host).toLowerCase();
  if (!getAllowedHosts().includes(cleanHost)) {
    return null;
  }

  const cleanPath = decodeURIComponent(targetPath || "").replace(/^\/+/, "");
  const query = search
    ? search
        .replace(/^\?/, "")
        .split("&")
        .filter((part) => !part.startsWith("scheme=") && !part.startsWith("host=") && !part.startsWith("path="))
        .join("&")
    : "";

  return `${scheme}://${cleanHost}/${cleanPath}${query ? `?${query}` : ""}`;
}

function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type, api-key");
}

module.exports = async function handler(req, res) {
  setCors(res);

  if (req.method === "OPTIONS") {
    res.status(204).end();
    return;
  }

  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const targetUrl = parseTarget(req);
  if (!targetUrl) {
    res.status(400).json({ error: "Invalid or disallowed proxy target" });
    return;
  }

  try {
    const upstream = await fetch(targetUrl, {
      method: "POST",
      headers: {
        Authorization: req.headers.authorization || "",
        "Content-Type": req.headers["content-type"] || "application/json",
        "api-key": req.headers["api-key"] || "",
      },
      body: JSON.stringify(req.body || {}),
    });

    const text = await upstream.text();
    const contentType = upstream.headers.get("content-type");
    if (contentType) {
      res.setHeader("Content-Type", contentType);
    }
    res.status(upstream.status).send(text);
  } catch (error) {
    res.status(502).json({
      error: "Proxy request failed",
      message: error instanceof Error ? error.message : String(error),
    });
  }
};
