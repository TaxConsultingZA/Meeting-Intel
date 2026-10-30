// @vitest-environment node
import { afterEach, expect, it, vi } from "vitest";
import { renderToPipeableStream } from "react-dom/server";
import { Writable } from "node:stream";
import { auth } from "@/lib/auth";
import { getMeeting } from "@/lib/api";
import Page from "../page";
vi.mock("@/lib/auth", () => ({ auth: vi.fn() }));
vi.mock("@/lib/api", () => ({ getMeeting: vi.fn() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn(), useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock("@/components/nav", () => ({ default: () => <nav>Dashboard navigation</nav> }));
vi.mock("../meeting-detail-client", () => ({ default: () => <article>Saved meeting content</article> }));
afterEach(() => vi.resetAllMocks());

it("streams navigation and compact labelled cards before the detail request resolves", async () => {
  vi.mocked(auth).mockResolvedValue({ user: { email: "owner@example.com" }, accessToken: "test" } as never);
  let finish!: (value: never) => void;
  vi.mocked(getMeeting).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const page = await Page({ params: Promise.resolve({ id: "meeting" }) });
  let html = "";
  let shellReady!: () => void;
  const ready = new Promise<void>(resolve => { shellReady = resolve; });
  const sink = new Writable({ write(chunk, _encoding, done) { html += chunk.toString(); done(); shellReady(); } });
  const complete = new Promise<void>(resolve => sink.on("finish", resolve));
  const stream = renderToPipeableStream(<html><body>{page}</body></html>, { onShellReady() { stream.pipe(sink); } });
  await ready;
  expect(html).toContain("Dashboard navigation");
  expect(html).toContain("Meeting details");
  expect(html).toContain("Summary loading");
  expect(html).toContain("Decisions loading");
  expect(html).not.toContain("h-96");
  expect(html).not.toContain("Saved meeting content");
  finish({ id: "meeting" } as never);
  await complete;
  expect(html).toContain("Saved meeting content");
  expect(getMeeting).toHaveBeenCalledOnce();
});

it("keeps navigation and renders a retry control when the detail API fails", async () => {
  vi.mocked(auth).mockResolvedValue({ user: { email: "owner@example.com" }, accessToken: "test" } as never);
  vi.mocked(getMeeting).mockRejectedValue(new Error("private upstream response"));
  const page = await Page({ params: Promise.resolve({ id: "meeting" }) });
  let html = "";
  const sink = new Writable({ write(chunk, _encoding, done) { html += chunk.toString(); done(); } });
  const complete = new Promise<void>(resolve => sink.on("finish", resolve));
  const stream = renderToPipeableStream(<html><body>{page}</body></html>, { onShellReady() { stream.pipe(sink); } });
  await complete;
  expect(html).toContain("Dashboard navigation");
  expect(html).toContain("Retry loading meeting");
  expect(html).not.toContain("private upstream response");
});


