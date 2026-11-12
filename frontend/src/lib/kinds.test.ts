import { describe, it, expect, afterEach } from "vitest";
import { isSupportedKind, isUsableName, supportedKinds } from "./kinds";

const told = document.createElement("meta");
told.name = "supported-extensions";

describe("the kinds of file the printer takes", () => {
  afterEach(() => told.remove());

  it("are those the server told the page, in order", () => {
    told.content = ".fdg, .CTB,,<x>";
    document.head.appendChild(told);
    expect(supportedKinds()).toEqual([".ctb", ".fdg"]);
  });

  it("take a name as the server will store it", () => {
    told.content = ".ctb";
    document.head.appendChild(told);
    expect(isSupportedKind("MODEL.CTB")).toBe(true);
    // The server drops the spaces around a name before it looks.
    expect(isSupportedKind("model.ctb ")).toBe(true);
    expect(isSupportedKind("model.ctb\u00a0")).toBe(true);
    expect(isSupportedKind("model.stl")).toBe(false);
  });

  it("take anything when the page was not told: the server says", () => {
    expect(isSupportedKind("model.stl")).toBe(true);
  });
});

describe("a name the server would take", () => {
  it.each(["model.ctb", ".hidden.ctb", "._model.ctb", " model.ctb ", "é.ctb"])(
    "is one: %j",
    (name) => expect(isUsableName(name)).toBe(true),
  );

  it.each([
    "bob's model.ctb",
    "what?.ctb",
    "a/b.ctb",
    "a\\b.ctb",
    "tab\there.ctb",
    "model.",
    "",
    "   ",
    `${"a".repeat(252)}.ctb`,
  ])("is not: %j", (name) => expect(isUsableName(name)).toBe(false));

  it("may be as long as 255 characters", () => {
    expect(isUsableName(`${"a".repeat(251)}.ctb`)).toBe(true);
  });
});
