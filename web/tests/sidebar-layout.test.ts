import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(fileURLToPath(new URL("../src/app/styles.css", import.meta.url)), "utf8");
const sidebar = readFileSync(
  fileURLToPath(new URL("../src/features/conversations/components/HistorySidebar.tsx", import.meta.url)),
  "utf8",
);

describe("history drawer off-canvas behavior", () => {
  it("moves the desktop drawer behind the viewport, including its rail offset", () => {
    expect(css).toContain("left:76px");
    expect(css).toContain("transform:translateX(calc(-100% - 76px))");
    expect(css).toContain(".chat-sidebar.open{transform:translateX(0)");
  });

  it("moves the mobile drawer fully beyond its left edge", () => {
    expect(css).toContain(".chat-sidebar{left:0;max-width:85vw;transform:translateX(-100%)}");
    expect(css).toContain(".chat-sidebar.open{transform:translateX(0)}");
  });

  it("prevents interaction and assistive technology focus when closed", () => {
    expect(css).toContain("visibility:hidden;pointer-events:none");
    expect(css).toContain("visibility:visible;pointer-events:auto");
    expect(sidebar).toContain("aria-hidden={!visible} inert={!visible}");
  });
});
