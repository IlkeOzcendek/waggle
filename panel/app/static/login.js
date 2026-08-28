const form = document.querySelector("#login-form");
const errorMessage = document.querySelector("#login-error");
const languageButton = document.querySelector("#login-language");
let language = localStorage.getItem("waggle-language") || "tr";
const loginEnglish = {
  "EDGE AI KOVAN İZLEME": "EDGE AI HIVE MONITORING",
  "Kovanları dinleyen yapay zekâ ile kolonilerinizi güvenle takip edin.": "Monitor your colonies with AI that listens to hives.",
  "YÖNETİM PANELİ": "MANAGEMENT PANEL", "Tekrar hoş geldiniz": "Welcome back",
  "Devam etmek için hesabınıza giriş yapın.": "Sign in to continue.",
  "Kullanıcı adı": "Username", "Parola": "Password", "Giriş yap": "Sign in",
};

function translateLogin() {
  document.documentElement.lang = language;
  document.querySelectorAll("body *").forEach(element => {
    if (element.children.length || !element.textContent.trim()) return;
    if (!element.dataset.tr) element.dataset.tr = element.textContent.trim();
    element.textContent = language === "en" ? (loginEnglish[element.dataset.tr] || element.dataset.tr) : element.dataset.tr;
  });
  languageButton.textContent = language === "tr" ? "EN" : "TR";
  document.title = language === "tr" ? "Waggle | Giriş" : "Waggle | Sign in";
}

languageButton.addEventListener("click", () => {
  language = language === "tr" ? "en" : "tr";
  localStorage.setItem("waggle-language", language);
  translateLogin();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorMessage.textContent = "";
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = language === "tr" ? "Giriş yapılıyor…" : "Signing in…";
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: form.username.value.trim(),
        password: form.password.value,
      }),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(body.detail || (language === "tr" ? "Giriş yapılamadı" : "Sign-in failed"));
    }
    window.location.replace("/");
  } catch (error) {
    errorMessage.textContent = error.message;
    button.disabled = false;
    button.textContent = language === "tr" ? "Giriş yap" : "Sign in";
  }
});

translateLogin();
