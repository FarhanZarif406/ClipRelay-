/**
 * English or Roman Urdu, per account.
 *
 * The pages are written in English. When an account chooses Roman Urdu, the text on screen is swapped for its Roman
 * Urdu from the dictionary (src/lib/ur.ts) as the pages draw it — whole lines, and lines with numbers in them through
 * patterns — so no page has to know about languages. Menu, section and tab names stay in English everywhere: anything
 * inside an element marked `data-i18n-skip` is left alone, and so are typed values, code and user content.
 */
import { UR, UR_PATTERNS } from "./ur";

export type Language = "en" | "ur";
const KEY = "cliprelay.language";
const ATTRIBUTES = ["placeholder", "title", "aria-label"] as const;
const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "CODE", "PRE", "TEXTAREA", "INPUT", "SELECT", "OPTION_SKIP"]);

let current: Language = (() => {
  try {
    return localStorage.getItem(KEY) === "ur" ? "ur" : "en";
  } catch {
    return "en";
  }
})();
const listeners = new Set<(lang: Language) => void>();
const originalText = new WeakMap<Text, string>();
const originalAttr = new WeakMap<Element, Record<string, string>>();
let observer: MutationObserver | null = null;
let busy = false;

export const language = () => current;

/** Roman Urdu for one English line, or the line itself when the dictionary has nothing for it. */
export function toUrdu(text: string): string {
  const trimmed = text.replace(/\s+/g, " ").trim();
  if (!trimmed) return text;
  const lead = text.match(/^\s*/)![0];
  const tail = text.match(/\s*$/)![0];
  const exact = UR[trimmed];
  if (exact !== undefined) return lead + exact + tail;
  for (const [pattern, replacement] of UR_PATTERNS) {
    if (pattern.test(trimmed)) return lead + trimmed.replace(pattern, replacement) + tail;
  }
  // A line made of parts ("Channels: 50 · Videos per day: 3"): each part on its own, and the name before a colon.
  if (trimmed.includes(" · ") || /^[^:]{2,40}: /.test(trimmed)) {
    const parts = trimmed.split(" · ").map(part => {
      const whole = UR[part] ?? UR_PATTERNS.find(([pattern]) => pattern.test(part));
      if (typeof whole === "string") return whole;
      if (whole) return part.replace(whole[0], whole[1]);
      const colon = part.match(/^([^:]{2,40}): (.*)$/);
      return colon && UR[colon[1]] ? `${UR[colon[1]]}: ${UR[colon[2]] ?? colon[2]}` : part;
    });
    const joined = parts.join(" · ");
    if (joined !== trimmed) return lead + joined + tail;
  }
  return text;
}

function skipped(node: Node): boolean {
  for (let el = node.nodeType === Node.ELEMENT_NODE ? (node as Element) : node.parentElement; el; el = el.parentElement) {
    if (SKIP_TAGS.has(el.tagName) || el.hasAttribute("data-i18n-skip") || (el as HTMLElement).isContentEditable) return true;
  }
  return false;
}

function translateText(node: Text) {
  if (skipped(node)) return;
  const shown = node.nodeValue ?? "";
  const known = originalText.get(node);
  // React wrote new English since our last change: that becomes the original.
  const english = known !== undefined && shown === toUrdu(known) ? known : shown;
  originalText.set(node, english);
  const urdu = toUrdu(english);
  if (urdu !== shown) node.nodeValue = urdu;
}

function translateAttributes(el: Element) {
  // A text box's own typed value is never touched, but its placeholder and tooltip are.
  if (el.hasAttribute("data-i18n-skip") || (el.parentElement && skipped(el.parentElement))) return;
  const saved = originalAttr.get(el) ?? {};
  for (const name of ATTRIBUTES) {
    const shown = el.getAttribute(name);
    if (shown === null) continue;
    const english = saved[name] !== undefined && shown === toUrdu(saved[name]) ? saved[name] : shown;
    saved[name] = english;
    const urdu = toUrdu(english);
    if (urdu !== shown) el.setAttribute(name, urdu);
  }
  originalAttr.set(el, saved);
}

function walk(root: Node, visit: (text: Text) => void, visitEl: (el: Element) => void) {
  if (root.nodeType === Node.TEXT_NODE) return visit(root as Text);
  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
  if (root.nodeType === Node.ELEMENT_NODE) visitEl(root as Element);
  const tree = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let node = tree.nextNode(); node; node = tree.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) visit(node as Text);
    else visitEl(node as Element);
  }
}

function translateAll(root: Node = document.body) {
  busy = true;
  walk(root, translateText, translateAttributes);
  busy = false;
}

function restoreAll() {
  walk(document.body, node => {
    const english = originalText.get(node);
    if (english !== undefined && node.nodeValue !== english) node.nodeValue = english;
  }, el => {
    const saved = originalAttr.get(el);
    if (saved) for (const [name, value] of Object.entries(saved)) if (el.getAttribute(name) !== value) el.setAttribute(name, value);
  });
}

function start() {
  if (observer) return;
  translateAll();
  observer = new MutationObserver(records => {
    if (busy) return;
    busy = true;
    for (const record of records) {
      if (record.type === "characterData") translateText(record.target as Text);
      else if (record.type === "attributes") translateAttributes(record.target as Element);
      else record.addedNodes.forEach(node => walk(node, translateText, translateAttributes));
    }
    busy = false;
  });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: [...ATTRIBUTES] });
}

function stop() {
  observer?.disconnect();
  observer = null;
  restoreAll();
}

/** Switch the whole app's language now, remember it in this browser, and tell whoever listens (the account is saved by the caller). */
export function setLanguage(lang: Language) {
  current = lang;
  try {
    localStorage.setItem(KEY, lang);
  } catch {
    /* private window: the account keeps the choice anyway */
  }
  document.documentElement.lang = lang === "ur" ? "ur-Latn" : "en";
  if (lang === "ur") start();
  else stop();
  listeners.forEach(fn => fn(lang));
}

export function onLanguage(fn: (lang: Language) => void) {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** Starts the translator for the language this browser last used, before the account is known. */
export function initLanguage() {
  if (current === "ur") setLanguage("ur");
}
