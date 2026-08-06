import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import os
import re

try:
    import mutagen
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, TRCK, APIC
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False

try:
    import musicbrainzngs
    musicbrainzngs.set_useragent("MetaDataFinder", "1.0", "https://example.com")
    MB_OK = True
except ImportError:
    MB_OK = False


class MetadataFinder(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Song Metadata Finder")
        self.geometry("800x650")

        self.files = []

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        file_frame = ttk.LabelFrame(main, text="Files", padding=5)
        file_frame.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(file_frame, text="Add MP3 Files", command=self.add_files).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(file_frame, text="Clear All", command=self.clear_files).pack(side=tk.LEFT)

        self.file_count = ttk.Label(file_frame, text="0 files")
        self.file_count.pack(side=tk.RIGHT)

        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        cols = ("File", "Artist", "Title", "Status")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=10)
        self.tree.heading("File", text="File")
        self.tree.heading("Artist", text="Artist")
        self.tree.heading("Title", text="Title")
        self.tree.heading("Status", text="Status")
        self.tree.column("File", width=250)
        self.tree.column("Artist", width=150)
        self.tree.column("Title", width=180)
        self.tree.column("Status", width=100)

        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        action_frame = ttk.Frame(main)
        action_frame.pack(fill=tk.X, pady=5)

        ttk.Button(action_frame, text="Fetch Metadata from MusicBrainz", command=self.fetch_metadata).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Write Tags to Files", command=self.write_tags).pack(side=tk.LEFT)

        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=5)

        log_frame = ttk.LabelFrame(main, text="Log", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log = scrolledtext.ScrolledText(log_frame, height=10, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)

    def log_msg(self, msg):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)
        self.update_idletasks()

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select MP3 Files",
            filetypes=[("MP3 files", "*.mp3"), ("All files", "*.*")]
        )
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                fname = os.path.basename(p)
                artist, title = self._parse_filename(fname)
                self.tree.insert("", tk.END, values=(fname, artist, title, "Pending"))
        self.file_count.configure(text=f"{len(self.files)} files")

    def clear_files(self):
        self.files.clear()
        self.tree.delete(*self.tree.get_children())
        self.file_count.configure(text="0 files")
        self.log_msg("Cleared file list.")

    def _parse_filename(self, fname):
        name = os.path.splitext(fname)[0]
        m = re.match(r'^(.+?)\s*[-–—]\s*(.+)$', name)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return "", name.strip()

    def fetch_metadata(self):
        if not MB_OK:
            messagebox.showerror("Missing Dependency", "musicbrainzngs not installed.\nRun: pip install musicbrainzngs")
            return
        if not self.files:
            messagebox.showinfo("No Files", "Add MP3 files first.")
            return
        t = threading.Thread(target=self._fetch_metadata_thread, daemon=True)
        t.start()

    def _fetch_metadata_thread(self):
        self.progress.start()
        items = self.tree.get_children()
        for i, item in enumerate(items):
            if i >= len(self.files):
                break
            fpath = self.files[i]
            fname = os.path.basename(fpath)
            vals = self.tree.item(item, "values")
            artist, title = vals[1], vals[2]
            if not artist and not title:
                self.tree.set(item, "Status", "No name info")
                continue
            self.tree.set(item, "Status", "Searching...")
            try:
                result = self._lookup_musicbrainz(artist, title)
                if result:
                    self.tree.set(item, "Status", "Found")
                    self.tree.set(item, "Artist", result.get("artist", artist))
                    self.tree.set(item, "Title", result.get("title", title))
                    self.files[i] = {
                        "path": fpath,
                        "meta": result
                    }
                    self.log_msg(f"Found: {result.get('artist')} - {result.get('title')}")
                else:
                    self.tree.set(item, "Status", "Not found")
                    self.files[i] = {"path": fpath, "meta": None}
                    self.log_msg(f"No match for: {fname}")
            except Exception as e:
                self.tree.set(item, "Status", "Error")
                self.files[i] = {"path": fpath, "meta": None}
                self.log_msg(f"Error looking up {fname}: {e}")
        self.progress.stop()
        self.log_msg("Metadata fetch complete.")

    def _lookup_musicbrainz(self, artist, title):
        query = {}
        if artist:
            query["artist"] = artist
        if title:
            query["recording"] = title
        if not query:
            return None

        result = musicbrainzngs.search_recordings(limit=1, **query)
        recordings = result.get("recording-list", [])
        if not recordings:
            return None

        rec = recordings[0]
        meta = {
            "title": rec.get("title", title),
            "artist": rec.get("artist-credit", [{}])[0].get("artist", {}).get("name", artist) if rec.get("artist-credit") else artist,
            "album": rec.get("release-list", [{}])[0].get("title", "") if rec.get("release-list") else "",
            "year": "",
            "track": "",
            "genre": "",
        }
        if rec.get("release-list"):
            release = rec["release-list"][0]
            if release.get("date"):
                meta["year"] = release["date"][:4]
            if release.get("medium-list"):
                medium = release["medium-list"][0]
                if medium.get("track-list"):
                    meta["track"] = str(medium["track-list"][0].get("number", ""))
                    if medium.get("position"):
                        meta["track"] = f"{medium['position']}.{meta['track']}"
            if release.get("tag-list"):
                meta["genre"] = release["tag-list"][0].get("name", "")
        return meta

    def write_tags(self):
        if not MUTAGEN_OK:
            messagebox.showerror("Missing Dependency", "mutagen not installed.\nRun: pip install mutagen")
            return
        if not self.files:
            messagebox.showinfo("No Files", "Nothing to write.")
            return
        if not any(isinstance(f, dict) and f.get("meta") for f in self.files):
            messagebox.showinfo("No Metadata", "Fetch metadata first before writing.")
            return
        t = threading.Thread(target=self._write_tags_thread, daemon=True)
        t.start()

    def _write_tags_thread(self):
        self.progress.start()
        written = 0
        for i, entry in enumerate(self.files):
            if not isinstance(entry, dict):
                continue
            meta = entry.get("meta")
            fpath = entry["path"]
            if not meta:
                continue
            try:
                try:
                    audio = mutagen.File(fpath, easy=False)
                    if audio is None:
                        self.log_msg(f"Cannot open: {os.path.basename(fpath)}")
                        continue
                    try:
                        tags = audio.tags
                    except AttributeError:
                        tags = None
                    if tags is None:
                        audio.add_tags()
                        tags = audio.tags

                    tags["TIT2"] = TIT2(encoding=3, text=meta["title"])
                    tags["TPE1"] = TPE1(encoding=3, text=meta["artist"])
                    if meta.get("album"):
                        tags["TALB"] = TALB(encoding=3, text=meta["album"])
                    if meta.get("year"):
                        tags["TDRC"] = TDRC(encoding=3, text=meta["year"])
                    if meta.get("genre"):
                        tags["TCON"] = TCON(encoding=3, text=meta["genre"])
                    if meta.get("track"):
                        tags["TRCK"] = TRCK(encoding=3, text=meta["track"])
                    apic_keys = [k for k in tags.keys() if k.startswith("APIC:")]
                    for k in apic_keys:
                        del tags[k]
                    audio.save()
                    written += 1
                    item_id = self.tree.get_children()[i]
                    self.tree.set(item_id, "Status", "Written")
                    self.log_msg(f"Written tags: {meta['artist']} - {meta['title']}")
                except mutagen.id3.ID3NoHeaderError:
                    audio = ID3(fpath)
                    self._write_id3_tags(audio, meta)
                    audio.save()
                    written += 1
                    item_id = self.tree.get_children()[i]
                    self.tree.set(item_id, "Status", "Written")
                    self.log_msg(f"Written tags: {meta['artist']} - {meta['title']}")
            except Exception as e:
                self.log_msg(f"Error writing {os.path.basename(fpath)}: {e}")
        self.progress.stop()
        self.log_msg(f"Done. Tags written to {written} file(s).")

    def _write_id3_tags(self, tags, meta):
        tags["TIT2"] = TIT2(encoding=3, text=meta["title"])
        tags["TPE1"] = TPE1(encoding=3, text=meta["artist"])
        if meta.get("album"):
            tags["TALB"] = TALB(encoding=3, text=meta["album"])
        if meta.get("year"):
            tags["TDRC"] = TDRC(encoding=3, text=meta["year"])
        if meta.get("genre"):
            tags["TCON"] = TCON(encoding=3, text=meta["genre"])
        if meta.get("track"):
            tags["TRCK"] = TRCK(encoding=3, text=meta["track"])
        apic_keys = [k for k in tags.keys() if k.startswith("APIC:")]
        for k in apic_keys:
            del tags[k]


if __name__ == "__main__":
    if not MUTAGEN_OK:
        print("mutagen is required. Install: pip install mutagen")
    if not MB_OK:
        print("musicbrainzngs is required. Install: pip install musicbrainzngs")
    app = MetadataFinder()
    app.mainloop()
