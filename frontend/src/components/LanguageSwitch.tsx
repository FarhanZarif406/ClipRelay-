import { useEffect, useState } from "react";
import { auth } from "@/api/endpoints";
import { language, onLanguage, setLanguage, type Language } from "@/lib/i18n";

/** The current language, kept in step with every switch on the page. */
function useLanguage(): [Language, (lang: Language) => void] {
  const [lang, setLang] = useState(language());
  useEffect(() => onLanguage(setLang), []);
  const choose = (next: Language) => {
    if (next === language()) return;
    setLanguage(next);
    auth.setLanguage(next).catch(() => undefined);  // the account keeps it for its other devices; the switch works anyway
  };
  return [lang, choose];
}

/** The small EN / UR switch in the top bar, on every page. */
export function LanguageToggle() {
  const [lang, choose] = useLanguage();
  return <div className="lang-toggle" data-i18n-skip role="group" aria-label="Language">
    <button type="button" className={lang === "en" ? "active" : ""} onClick={() => choose("en")} title="English">EN</button>
    <button type="button" className={lang === "ur" ? "active" : ""} onClick={() => choose("ur")} title="Roman Urdu">UR</button>
  </div>;
}

/** The language board on the Dashboard: English or Roman Urdu, for the whole app. */
export function LanguageBoard() {
  const [lang, choose] = useLanguage();
  return <div className="lang-board" data-i18n-skip>
    <div className="lang-board-text">
      <b>{lang === "ur" ? "Zubaan (Language)" : "Language (Zubaan)"}</b>
      <span>{lang === "ur" ? "Poori app ki zubaan chunein. Menu aur sections ke naam English hi rahenge." : "Choose the language of the whole app. Menu and section names stay in English."}</span>
    </div>
    <div className="lang-board-options">
      <button type="button" className={lang === "en" ? "active" : ""} onClick={() => choose("en")}><b>English</b><small>Everything in English</small></button>
      <button type="button" className={lang === "ur" ? "active" : ""} onClick={() => choose("ur")}><b>Roman Urdu</b><small>Sab kuch Roman Urdu mein</small></button>
    </div>
  </div>;
}
