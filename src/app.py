from __future__ import annotations
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from .carver import DeepCarver

class RecoveryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Camera Footage Recovery — Imou / Dahua")
        self.root.geometry("1000x720")
        self.root.minsize(820, 600)
        self.carver = None
        self.worker = None
        self._build()

    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("Arial", 18, "bold"), foreground="#123c55")
        style.configure("Section.TLabel", font=("Arial", 11, "bold"), foreground="#176b62")
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Camera Footage Recovery", style="Header.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Recover video fragments from an SD-card image, DVR disk image, or read-only device").pack(anchor="w", pady=(2,14))

        srcbox = ttk.LabelFrame(outer, text="Source", padding=12)
        srcbox.pack(fill="x")
        self.source_type = tk.StringVar(value="image")
        ttk.Radiobutton(srcbox, text="Disk image (recommended)", variable=self.source_type,
                        value="image").grid(row=0,column=0,sticky="w")
        ttk.Radiobutton(srcbox, text="Physical device (advanced / read-only)", variable=self.source_type,
                        value="device").grid(row=1,column=0,sticky="w")
        self.source = tk.StringVar()
        ttk.Entry(srcbox, textvariable=self.source).grid(row=0,column=1,rowspan=2,sticky="ew",padx=8)
        ttk.Button(srcbox,text="Browse…",command=self.browse_source).grid(row=0,column=2,rowspan=2)
        srcbox.columnconfigure(1,weight=1)

        outbox=ttk.LabelFrame(outer,text="Recovery options",padding=12)
        outbox.pack(fill="x",pady=10)
        ttk.Label(outbox,text="Output folder").grid(row=0,column=0,sticky="w")
        self.output=tk.StringVar(value=str(Path.home()/"CameraRecovery"/"Recovered"))
        ttk.Entry(outbox,textvariable=self.output).grid(row=0,column=1,sticky="ew",padx=8)
        ttk.Button(outbox,text="Browse…",command=self.browse_output).grid(row=0,column=2)
        self.validate=tk.BooleanVar(value=True)
        self.playable=tk.BooleanVar(value=False)
        ttk.Checkbutton(outbox,text="Validate with ffprobe (if installed)",variable=self.validate).grid(row=1,column=0,columnspan=2,sticky="w",pady=5)
        ttk.Checkbutton(outbox,text="Export playable files only",variable=self.playable).grid(row=1,column=2,sticky="w")
        ttk.Label(outbox,text="Maximum size per recovered fragment (MB)").grid(row=2,column=0,sticky="w")
        self.max_mb=tk.StringVar(value="512")
        ttk.Entry(outbox,textvariable=self.max_mb,width=12).grid(row=2,column=1,sticky="w",padx=8)
        outbox.columnconfigure(1,weight=1)

        controls=ttk.Frame(outer); controls.pack(fill="x",pady=5)
        self.start_btn=ttk.Button(controls,text="Start deep scan",command=self.start_scan)
        self.start_btn.pack(side="left")
        self.stop_btn=ttk.Button(controls,text="Stop",command=self.stop_scan,state="disabled")
        self.stop_btn.pack(side="left",padx=8)
        self.status=tk.StringVar(value="Ready. Use a disk image where possible; never write to the source card.")
        ttk.Label(outer,text="Progress",style="Section.TLabel").pack(anchor="w",pady=(12,3))
        self.bar=ttk.Progressbar(outer,mode="determinate",maximum=100)
        self.bar.pack(fill="x")
        ttk.Label(outer,textvariable=self.status).pack(anchor="w",pady=5)
        self.counts=tk.StringVar(value="Found: 0  |  Exported: 0")
        ttk.Label(outer,textvariable=self.counts).pack(anchor="w")

        ttk.Label(outer,text="Recovered fragments",style="Section.TLabel").pack(anchor="w",pady=(12,4))
        tableframe=ttk.Frame(outer); tableframe.pack(fill="both",expand=True)
        cols=("name","type","offset","size","valid","path")
        self.tree=ttk.Treeview(tableframe,columns=cols,show="headings")
        for c,label,width in [("name","Name",240),("type","Format",150),("offset","Source offset",130),("size","Size",90),("valid","Validated",90),("path","Saved file",260)]:
            self.tree.heading(c,text=label); self.tree.column(c,width=width,anchor="w")
        vs=ttk.Scrollbar(tableframe,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left",fill="both",expand=True); vs.pack(side="right",fill="y")
        ttk.Label(outer,text="Note: recovery is not guaranteed. DHAV is a proprietary Dahua/Imou stream; some recovered fragments may need the camera vendor's player.",wraplength=940).pack(anchor="w",pady=(8,0))

    def browse_source(self):
        if self.source_type.get()=="image":
            path=filedialog.askopenfilename(title="Select disk image",filetypes=[("Disk images","*.img *.dd *.bin *.raw"),("All files","*.*")])
        else:
            path=filedialog.askopenfilename(title="Select device path (Linux /dev/...)",filetypes=[("All files","*")])
        if path: self.source.set(path)

    def browse_output(self):
        path=filedialog.askdirectory()
        if path: self.output.set(path)

    def start_scan(self):
        source=self.source.get().strip()
        if not source or not os.path.exists(source):
            messagebox.showerror("Source required","Select an existing disk image or device path."); return
        if self.source_type.get()=="device" and os.name!="posix":
            messagebox.showerror("Unsupported","Physical device scanning is currently supported only on Linux/macOS paths."); return
        try: max_mb=int(self.max_mb.get())
        except ValueError:
            messagebox.showerror("Invalid value","Maximum fragment size must be a whole number."); return
        if max_mb<1:
            messagebox.showerror("Invalid value","Maximum fragment size must be at least 1 MB."); return
        if self.source_type.get()=="device":
            ok=messagebox.askyesno("Read-only warning","This tool opens the selected device for reading only. Create a full image first whenever possible. Continue?")
            if not ok: return
        if Path(self.output.get()).resolve()==Path(source).resolve():
            messagebox.showerror("Unsafe output","Choose a separate output folder, not the source file/device."); return
        self.tree.delete(*self.tree.get_children())
        self.bar["value"]=0; self.start_btn["state"]="disabled"; self.stop_btn["state"]="normal"
        self.carver=DeepCarver(source,max_clip_mb=max_mb)
        self.worker=threading.Thread(target=self._scan_worker,daemon=True)
        self.worker.start()

    def _scan_worker(self):
        def progress(done,total,found):
            self.root.after(0,self._progress,done,total,found)
        try:
            hits=self.carver.scan(self.output.get(),progress=progress,
                                  validate=self.validate.get(),export_playable_only=self.playable.get())
            self.root.after(0,self._finished,hits,None)
        except Exception as exc:
            self.root.after(0,self._finished,None,str(exc))

    def _progress(self,done,total,found):
        pct=(done/total*100) if total else 0
        self.bar["value"]=pct
        self.status.set(f"Scanning… {done/1024**3:.2f} / {total/1024**3:.2f} GB ({pct:.1f}%)")
        self.counts.set(f"Found: {found}  |  Exported: {sum(1 for x in self.tree.get_children())}")

    def _finished(self,hits,error):
        self.start_btn["state"]="normal"; self.stop_btn["state"]="disabled"
        if error:
            self.status.set("Scan failed.")
            messagebox.showerror("Scan error",error); return
        exported=0
        for hit in hits:
            if hit.path:
                exported+=1
                self.tree.insert("", "end", values=(hit.path.name,hit.signature.name,
                    f"0x{hit.offset:X}",f"{hit.size/1024/1024:.2f} MB",
                    ("Yes" if hit.valid else "No/Unknown") if self.validate.get() else "Not checked",
                    str(hit.path)))
        self.counts.set(f"Found: {len(hits)}  |  Exported: {exported}")
        self.status.set("Scan stopped." if self.carver.cancelled else "Scan complete.")
        messagebox.showinfo("Recovery finished",f"Signatures found: {len(hits)}\\nFiles exported: {exported}\\n\\nReview the recovered fragments before relying on them.")

    def stop_scan(self):
        if self.carver: self.carver.stop()
        self.status.set("Stopping scan…")

def main():
    root=tk.Tk()
    RecoveryApp(root)
    root.mainloop()
