import { createChat } from "https://cdn.jsdelivr.net/npm/@n8n/chat@0.46.0/dist/chat.bundle.es.js";

const RW = window.RW || { lang: "en", i18n: {} };

function t(key) {
  return (RW.i18n && RW.i18n[key]) || key;
}

const copy = {
  title: t("chat.title"),
  subtitle: t("chat.subtitle"),
  footer: t("chat.footer"),
  getStarted: t("chat.get_started"),
  inputPlaceholder: t("chat.placeholder"),
};

const options = {
  webhookUrl: "/api/v1/chat/n8n",
  webhookConfig: { method: "POST", headers: {} },
  loadPreviousSession: true,
  showWelcomeScreen: false,
  defaultLanguage: RW.lang === "es" ? "es" : "en",
  initialMessages: [copy.subtitle],
  i18n: { en: copy, es: copy },
};

if (RW.n8nChatMode) {
  const target = document.getElementById("n8n-chat-full");
  if (target) {
    createChat({ ...options, target: "#n8n-chat-full", mode: "fullscreen" });
  }
} else {
  createChat({ ...options, target: "#n8n-chat", mode: "window" });
}
