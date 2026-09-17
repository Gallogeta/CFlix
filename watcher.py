import os
import time
import threading
import subprocess
from typing import Set

from config import get_watch_dir, cfg
from metadata import clean_filename, search_imdb
from processor import process_and_ingest
from collections_manager import collections_mgr
from logger import emit_log

class DirectoryWatcher:
    def __init__(self):
        self.enabled = cfg.get("WATCHER_ENABLED", True)
        self.thread = None
        self.running = False
        self.file_sizes = {}

    @property
    def interval(self) -> int:
        return cfg.get("WATCHER_INTERVAL", 10)

    def is_file_ready(self, file_path: str) -> bool:
        # Check if fuser shows any process writing to the file
        try:
            check_proc = subprocess.run(["fuser", file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if check_proc.stdout.strip():
                return False
        except Exception:
            pass

        # Check if file size is non-zero and stable for at least 6 seconds
        try:
            current_size = os.path.getsize(file_path)
        except OSError:
            return False

        if current_size == 0:
            return False

        prev_size, prev_time = self.file_sizes.get(file_path, (None, None))
        now = time.time()

        if prev_size is None or prev_size != current_size:
            self.file_sizes[file_path] = (current_size, now)
            return False
        else:
            if now - prev_time >= 6:
                return True
            return False

    def watch_loop(self):
        emit_log(f"Watcher started on directory: {get_watch_dir()}")
        while self.running:
            if not self.enabled:
                time.sleep(2)
                continue

            watch_dir = get_watch_dir()
            if not os.path.exists(watch_dir):
                time.sleep(self.interval)
                continue

            try:
                all_entries = os.listdir(watch_dir)
            except Exception as e:
                time.sleep(self.interval)
                continue

            valid_files = [
                os.path.join(watch_dir, f)
                for f in all_entries
                if f.lower().endswith((".mp4", ".mkv", ".avi", ".mov")) and not f.startswith(".")
            ]

            ready_files = []
            for vf in valid_files:
                if self.is_file_ready(vf):
                    ready_files.append(vf)

            for rf in ready_files:
                fname = os.path.basename(rf)
                emit_log(f"Watcher detected ready file: '{fname}'")
                meta = clean_filename(fname)
                title = meta["cleaned_title"]
                
                # Check IMDb match
                imdb_matches = search_imdb(title)
                matched_title = title
                matched_year = meta.get("guessed_year")
                imdb_id = None

                if imdb_matches:
                    best = imdb_matches[0]
                    matched_title = best["title"]
                    matched_year = best.get("year", matched_year)
                    imdb_id = best.get("imdb_id")
                    emit_log(f"IMDb Match for '{title}': '{matched_title}' ({matched_year}) [{imdb_id}]")

                cat = "series" if meta["is_series"] else "movies"
                res = process_and_ingest(
                    src_file=rf,
                    target_category=cat,
                    title=matched_title,
                    year=matched_year,
                    imdb_id=imdb_id,
                    season=meta.get("season"),
                    episode=meta.get("episode"),
                    overwrite=True
                )

                if res.get("success"):
                    # Auto-sync collections if movie was ingested
                    if cat == "movies":
                        threading.Thread(target=collections_mgr.sync_all_collections, daemon=True).start()

                # Remove from size tracker
                self.file_sizes.pop(rf, None)

            time.sleep(self.interval)

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self.watch_loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.running = False

    def toggle(self, state: bool):
        self.enabled = state
        emit_log(f"Watcher auto-ingestion toggled to: {'ENABLED' if state else 'DISABLED'}")

watcher = DirectoryWatcher()
