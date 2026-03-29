"""
Robin Human Adapter - Adapts human_simulation.py engines for Windows-MCP tools.
"""
import json, math, random, string, time
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass

class TimingEngineBase:
    def __init__(self, base_delay=0.5, variance=0.3):
        self.base_delay = base_delay
        self.variance = variance
    def get_delay(self, factor=1.0):
        return max(0.1, random.gauss(self.base_delay * factor, self.base_delay * self.variance))
    def get_reading_time(self, content_length, wpm=200):
        return max(1.0, (content_length / 6 / wpm) * 60 * random.uniform(0.8, 1.2))
    def get_burst_delay(self):
        return random.uniform(0.05, 0.15)

class MouseEngineBase:
    def __init__(self, screen_width=1920, screen_height=1080):
        self.screen_width = screen_width
        self.screen_height = screen_height
    def generate_bezier_path(self, start, end, num_points=20):
        x0, y0 = start; x3, y3 = end
        x1 = x0 + random.uniform(-100, 100); y1 = y0 + random.uniform(-50, 50)
        x2 = x3 + random.uniform(-100, 100); y2 = y3 + random.uniform(-50, 50)
        path = []
        for i in range(num_points):
            t = i / (num_points - 1)
            x = (1-t)**3*x0 + 3*(1-t)**2*t*x1 + 3*(1-t)*t**2*x2 + t**3*x3
            y = (1-t)**3*y0 + 3*(1-t)**2*t*y1 + 3*(1-t)*t**2*y2 + t**3*y3
            path.append((int(x), int(y)))
        return path
    def generate_scroll_sequence(self, pixels, direction="down"):
        seq, rem = [], pixels
        speed = random.randint(50, 150)
        while rem > 0:
            amt = int(min(speed, rem) * random.uniform(0.8, 1.2))
            seq.append({"direction": direction, "amount": amt}); rem -= amt
        return seq

class KeyboardEngineBase:
    def __init__(self, typo_rate=0.02, correction_rate=0.8):
        self.typo_rate = typo_rate; self.correction_rate = correction_rate
    def generate_keystroke_sequence(self, text):
        seq = []
        for ch in text:
            if random.random() < self.typo_rate:
                seq.append({"type": "keystroke", "char": random.choice(string.ascii_letters)})
                seq.append({"type": "delay", "duration": random.uniform(0.3, 0.8)})
                if random.random() < self.correction_rate:
                    seq.append({"type": "keystroke", "char": "BACKSPACE"})
                    seq.append({"type": "delay", "duration": random.uniform(0.1, 0.3)})
            seq.append({"type": "keystroke", "char": ch})
            seq.append({"type": "delay", "duration": random.uniform(0.05, 0.25 if ch in " .,;:!?" else 0.15)})
        return seq

# Always use our own portable engines (human_simulation.py has incompatible API)
TimingEngine = TimingEngineBase
MouseEngine = MouseEngineBase
KeyboardEngine = KeyboardEngineBase
@dataclass
class MCPToolCall:
    tool: str
    args: Dict[str, Any]
    def to_dict(self): return {"tool": self.tool, "args": self.args}

class RobinHumanInterface:
    """Adapts human simulation engines for Windows-MCP tools."""
    def __init__(self, screen_width=1920, screen_height=1080, base_delay=0.5, mouse_variance=0.3, typo_rate=0.02):
        self.timing = TimingEngine(base_delay=base_delay, variance=mouse_variance)
        self.mouse = MouseEngine(screen_width=screen_width, screen_height=screen_height)
        self.keyboard = KeyboardEngine(typo_rate=typo_rate, correction_rate=0.8)
        self.sw = screen_width; self.sh = screen_height
    def _d(s2, s): return MCPToolCall("_delay", {"seconds": max(0.1, s)}).to_dict()
    def _m(s2, x, y): return MCPToolCall("windows-mcp.Move", {"x": x, "y": y}).to_dict()
    def _c(s2, x, y, b="left"): return MCPToolCall("windows-mcp.Click", {"x": x, "y": y, "button": b}).to_dict()
    def _t(s2, txt): return MCPToolCall("windows-mcp.Type", {"text": txt}).to_dict()
    def _scr(s2, d, a): return MCPToolCall("windows-mcp.Scroll", {"direction": d, "amount": a}).to_dict()
    def _snap(s2, v=False): return MCPToolCall("windows-mcp.Snapshot", {"use_vision": v}).to_dict()

    def human_click(self, x, y):
        calls = [self._d(self.timing.get_delay(0.5))]
        path = self.mouse.generate_bezier_path((self.sw//2, self.sh//2), (x, y), random.randint(15, 25))
        dt = self.timing.get_delay(1.5) / len(path)
        for p in path:
            calls += [self._m(p[0], p[1]), self._d(dt)]
        calls += [self._c(x, y), self._d(self.timing.get_delay(0.3))]
        return calls

    def human_type(self, text):
        calls = [self._d(self.timing.get_delay(0.7))]
        buf = ""
        for a in self.keyboard.generate_keystroke_sequence(text):
            if a["type"] == "keystroke":
                if a["char"] == "BACKSPACE":
                    if buf: calls.append(self._t(buf)); buf = ""
                    calls.append(MCPToolCall("_keystroke", {"key": "BackSpace"}).to_dict())
                else: buf += a["char"]
            elif a["type"] == "delay":
                if buf: calls.append(self._t(buf)); buf = ""
                calls.append(self._d(a["duration"]))
        if buf: calls.append(self._t(buf))
        return calls

    def human_scroll(self, pixels, direction="down"):
        calls = [self._d(self.timing.get_delay(0.5))]
        seq = self.mouse.generate_scroll_sequence(pixels, direction)
        for i, s in enumerate(seq):
            calls.append(self._scr(s["direction"], s["amount"]))
            if i < len(seq)-1: calls.append(self._d(self.timing.get_burst_delay()))
        calls.append(self._d(self.timing.get_delay(0.2)))
        return calls

    def human_navigate(self, url):
        calls = [self._d(self.timing.get_delay(1.0))]
        prefix = "" if url.startswith(("http://", "https://")) else "https://"
        calls.append(MCPToolCall("windows-mcp.Shell", {"command": f'start "{prefix}{url}"'}).to_dict())
        calls.append(self._d(self.timing.get_delay(3.0)))
        return calls

    def human_read_pause(self, content_length):
        return [self._d(max(1.0, self.timing.get_reading_time(content_length)))]

def create_human_interface(sw=1920, sh=1080):
    return RobinHumanInterface(screen_width=sw, screen_height=sh)

if __name__ == "__main__":
    i = create_human_interface()
    print(f"Click: {len(i.human_click(500, 300))} calls")
    print(f"Type: {len(i.human_type('Hello'))} calls")
    print(f"Scroll: {len(i.human_scroll(500))} calls")
