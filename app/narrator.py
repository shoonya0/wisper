"""Narration pipeline: split -> synthesize sentence k+1 while sentence k plays -> stop.

Narration spec _docs/specs/2026-10-07-kokoro-narration.md §3.3, §5.2, §5.4. A leaf module
with no Tk or device code: synth, play and split are passed in, so it runs with fakes.

Threads: speak() runs on the TTS worker (the only thread that synthesizes) and blocks
until the narration ends; it plays on a short-lived player thread of its own. stop() and
begin() are the only calls that are safe from the UI thread. A generation id makes a
stop that arrives before speak() starts, and any synthesis that finishes after a stop,
harmless.
"""

import queue
import threading

WAIT_S = 0.02   # how often a waiting worker re-checks for stop


class Narrator:
    """Exactly one terminal callback per speak(): on_done(stopped) or on_error(message).

    synth(piece, **options) -> samples; play(samples, stop_event) -> None, returning early
    when stop_event is set and raising on a device error; split(text) -> pieces.
    """

    def __init__(self, synth, play, split, on_done, on_error):
        self._synth = synth
        self._play = play
        self._split = split
        self._on_done = on_done
        self._on_error = on_error
        self._lock = threading.Lock()
        self._gen = 0
        self._stop = threading.Event()

    def stop(self):
        """Stop the narration in progress (any thread). Returns the new generation id."""
        with self._lock:
            self._gen += 1
            self._stop.set()
            return self._gen

    def begin(self):
        """UI thread, before queueing a speak: stops anything playing; pass the id to speak()."""
        return self.stop()

    def speak(self, gen, text, **options):
        """Narrate text (TTS worker thread). Returns when it finished, stopped or failed."""
        with self._lock:
            if gen != self._gen:              # stopped (or superseded) before it started
                stale = True
            else:
                stale = False
                stop = self._stop = threading.Event()
        if stale:
            self._on_done(True)
            return
        try:
            pieces = self._split(text)
        except Exception as e:
            self._on_error(str(e) or type(e).__name__)
            return
        if not pieces:
            self._on_done(False)
            return

        ready = queue.Queue()                 # samples for the player; None = no more
        taken = threading.Semaphore(0)        # released when the player starts a piece
        failure = []

        def player():
            while (samples := ready.get()) is not None:
                taken.release()
                if stop.is_set():
                    continue                  # drain without playing
                try:
                    self._play(samples, stop)
                except Exception as e:
                    failure.append(e)
                    stop.set()

        thread = threading.Thread(target=player, name="narration-player", daemon=True)
        thread.start()
        try:
            for piece in pieces:
                if stop.is_set():
                    break
                samples = self._synth(piece, **options)
                if stop.is_set():
                    break                     # a late result after stop is dropped
                ready.put(samples)
                # One ahead, never more: synthesize the next piece once this one is playing.
                while not taken.acquire(timeout=WAIT_S) and not stop.is_set():
                    pass
        except Exception as e:
            failure.append(e)                 # pieces already queued still play
        ready.put(None)
        thread.join()

        if failure:
            self._on_error(str(failure[0]) or type(failure[0]).__name__)
        else:
            self._on_done(stop.is_set())
