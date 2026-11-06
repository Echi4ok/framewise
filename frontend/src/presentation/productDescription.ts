import { formatUiText } from "./text";

const omitted = new Set([
  "SCRIPT",
  "STYLE",
  "TEMPLATE",
  "NOSCRIPT",
  "IFRAME",
  "OBJECT",
  "SVG",
  "CANVAS",
]);
const blocks = new Set([
  "P",
  "DIV",
  "SECTION",
  "ARTICLE",
  "HEADER",
  "FOOTER",
  "BLOCKQUOTE",
  "PRE",
  "H1",
  "H2",
  "H3",
  "H4",
  "H5",
  "H6",
]);

export function productDescriptionText(source: string): string {
  const template = document.createElement("template");
  template.innerHTML = source;
  const hasMarkup = template.content.querySelector("*") !== null;

  function render(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = (node.textContent ?? "").replace(/\u00a0/g, " ");
      return hasMarkup ? text.replace(/\s+/g, " ") : text;
    }
    if (!(node instanceof Element)) return "";
    const tag = node.tagName.toUpperCase();
    if (omitted.has(tag)) return "";
    if (tag === "BR") return "\n";
    if (tag === "UL" || tag === "OL") {
      const items = Array.from(node.childNodes, render)
        .map((item) => item.trim())
        .filter(Boolean);
      return `\n${items.join("\n")}\n`;
    }
    const children = Array.from(node.childNodes, render).join("");
    if (tag === "LI") {
      if (!children.trim()) return "";
      const list = node.parentElement;
      let marker = "•";
      if (list?.tagName === "OL") {
        const start = Number.parseInt(list.getAttribute("start") ?? "1", 10);
        const index = Array.from(list.children)
          .filter((item) => item.tagName === "LI")
          .indexOf(node);
        marker = `${(Number.isFinite(start) ? start : 1) + index}.`;
      }
      return `\n${marker} ${children.trim()}\n`;
    }
    if (tag === "TR") return `\n${children.trim()}\n`;
    if (tag === "TD" || tag === "TH") return `${children.trim()} `;
    if (blocks.has(tag)) return `\n\n${children.trim()}\n\n`;
    return children;
  }

  return formatUiText(Array.from(template.content.childNodes, render).join(""))
    .replace(/[\t ]+\n/g, "\n")
    .replace(/\n[\t ]+/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
