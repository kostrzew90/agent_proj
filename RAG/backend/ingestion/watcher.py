"""
RAG System — Watch Folder Monitor
Monitors a directory for new files and triggers document processing.
"""

import logging
import time
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent

from config import settings
from ingestion.parser import is_supported

logger = logging.getLogger("rag.watcher")


class DocumentHandler(FileSystemEventHandler):
    """Handle new files in the watch folder."""

    def __init__(self, callback):
        """
        Args:
            callback: Function to call with the file path when a new file is detected.
                      Signature: callback(file_path: str) -> None
        """
        self.callback = callback
        self._processing: set[str] = set()

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        self._handle_file(event.src_path)

    def on_moved(self, event: FileMovedEvent):
        if event.is_directory:
            return
        self._handle_file(event.dest_path)

    def _handle_file(self, file_path: str):
        """Process a newly detected file."""
        if file_path in self._processing:
            return

        if not is_supported(file_path):
            logger.debug(f"Ignoring unsupported file: {file_path}")
            return

        # Wait briefly for file write to complete
        path = Path(file_path)
        try:
            initial_size = path.stat().st_size
            time.sleep(1)
            if path.stat().st_size != initial_size:
                # File still being written, wait more
                time.sleep(3)
        except OSError:
            return

        self._processing.add(file_path)
        logger.info(f"New file detected: {path.name}")

        try:
            self.callback(file_path)
        except Exception as e:
            logger.error(f"Failed to process {path.name}: {e}")
        finally:
            self._processing.discard(file_path)


class FolderWatcher:
    """Watches a folder for new documents and triggers processing."""

    def __init__(self, callback):
        """
        Args:
            callback: Function called with file path for each new file.
        """
        self.watch_path = settings.watch_folder.path
        self.callback = callback
        self._observer: Observer | None = None

    def start(self):
        """Start watching the folder."""
        watch_dir = Path(self.watch_path)
        watch_dir.mkdir(parents=True, exist_ok=True)

        handler = DocumentHandler(self.callback)
        self._observer = Observer()
        self._observer.schedule(handler, str(watch_dir), recursive=False)
        self._observer.start()
        logger.info(f"Watch folder started: {self.watch_path}")

    def stop(self):
        """Stop watching."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Watch folder stopped.")

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
