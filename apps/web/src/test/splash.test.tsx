import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SPLASH_SEEN_KEY, SplashScreen } from "@/components/layout/SplashScreen";
import { useSettings } from "@/store/settings";

const realMatchMedia = window.matchMedia;

function reduceMotion(reduce: boolean) {
  window.matchMedia = ((query: string) => ({ ...realMatchMedia(query), matches: reduce && query.includes("reduced-motion") })) as typeof window.matchMedia;
}

describe("SplashScreen", () => {
  beforeEach(() => {
    sessionStorage.clear();
    useSettings.setState({ language: "en", showIntro: true });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  });
  afterEach(() => {
    window.matchMedia = realMatchMedia;
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("plays the muted intro in a small window and closes on Skip, once per session", async () => {
    const { container, unmount } = render(<SplashScreen />);
    expect(screen.getByRole("dialog", { name: "ARVA is starting" })).toBeInTheDocument();
    const video = container.querySelector("video")!;
    expect(video).toHaveAttribute("src", "/intro/arva-intro.mp4");
    expect(video.muted).toBe(true);
    expect(screen.getByText(`ARVA ${__ARVA_VERSION__}`)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(sessionStorage.getItem(SPLASH_SEEN_KEY)).toBe("1");
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await act(() => new Promise((r) => setTimeout(r, 450)));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    unmount();
    render(<SplashScreen />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes with Escape and when the video ends or fails", async () => {
    const first = render(<SplashScreen />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(sessionStorage.getItem(SPLASH_SEEN_KEY)).toBe("1");
    first.unmount();

    sessionStorage.clear();
    const second = render(<SplashScreen />);
    fireEvent(second.container.querySelector("video")!, new Event("ended"));
    expect(sessionStorage.getItem(SPLASH_SEEN_KEY)).toBe("1");
    second.unmount();

    sessionStorage.clear();
    const third = render(<SplashScreen />);
    fireEvent(third.container.querySelector("video")!, new Event("error"));
    expect(sessionStorage.getItem(SPLASH_SEEN_KEY)).toBe("1");
  });

  it("is not shown when turned off in Settings", () => {
    useSettings.setState({ showIntro: false });
    render(<SplashScreen />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows a still image instead of the animation when reduced motion is requested", () => {
    vi.useFakeTimers();
    reduceMotion(true);
    const { container } = render(<SplashScreen />);
    expect(container.querySelector("video")).toBeNull();
    expect(screen.getByRole("img")).toHaveAttribute("src", "/intro/arva-intro-end.jpg");
    act(() => vi.advanceTimersByTime(1500));
    act(() => vi.advanceTimersByTime(400));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("is translated", () => {
    useSettings.setState({ language: "es" });
    render(<SplashScreen />);
    expect(screen.getByRole("dialog", { name: "ARVA se está iniciando" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Saltar" })).toBeInTheDocument();
  });
});
