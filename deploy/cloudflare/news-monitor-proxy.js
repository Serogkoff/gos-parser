const UPSTREAM_ORIGIN = "https://ria.tail196372.ts.net";
const PUBLIC_HOST = "news-monitor.ru";

export default {
  async fetch(request) {
    const publicUrl = new URL(request.url);
    if (publicUrl.hostname !== PUBLIC_HOST) {
      return new Response("Unknown host", { status: 400 });
    }

    const upstreamBase = new URL(UPSTREAM_ORIGIN);
    const upstreamUrl = new URL(publicUrl.pathname + publicUrl.search, upstreamBase);
    const upstreamRequest = new Request(upstreamUrl, request);
    const clientAddress = request.headers.get("CF-Connecting-IP");

    upstreamRequest.headers.set("X-Forwarded-Host", publicUrl.host);
    upstreamRequest.headers.set("X-Forwarded-Proto", "https");
    upstreamRequest.headers.set("X-Forwarded-Port", "443");
    if (clientAddress) {
      upstreamRequest.headers.set("X-Forwarded-For", clientAddress);
    }

    const upstreamResponse = await fetch(upstreamRequest, { redirect: "manual" });
    const responseHeaders = new Headers(upstreamResponse.headers);
    const location = responseHeaders.get("Location");

    // Flask обычно возвращает относительные адреса. Если появится абсолютный
    // адрес Funnel, оставляем пользователя на публичном домене.
    if (location) {
      const redirectUrl = new URL(location, upstreamUrl);
      if (redirectUrl.origin === upstreamBase.origin) {
        redirectUrl.protocol = publicUrl.protocol;
        redirectUrl.host = publicUrl.host;
        responseHeaders.set("Location", redirectUrl.toString());
      }
    }

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  },
};
