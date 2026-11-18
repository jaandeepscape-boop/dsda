import os

main_path = r"C:\Users\jaand\HypeClipper\main.py"
with open(main_path, "r", encoding="utf-8") as f:
    content = f.read()

split_marker = "# --------------------------------------------------------------------------\n# UI\n# --------------------------------------------------------------------------"

if split_marker not in content:
    print("ERROR: split marker not found!")
    exit(1)

core_logic = content.split(split_marker)[0]

new_ui_code = split_marker + """
# BridgeClip Studio UI
# --------------------------------------------------------------------------
APP_TITLE = "BridgeClip"

BG_DARK = "#0b0d11"
SIDEBAR_BG = "#11141b"
CARD_BG = "#161922"
CARD_BORDER = "#232836"
CARD_ACTIVE_BG = "#172236"
CARD_ACTIVE_BORDER = "#3b82f6"
TEXT_MAIN = "#f8fafc"
TEXT_MUTED = "#94a3b8"
TEXT_DIM = "#64748b"
ACCENT_BLUE = "#2563eb"
ACCENT_BLUE_HOVER = "#1d4ed8"
ACCENT_GREEN = "#10b981"
BTN_DARK = "#1d212c"
BTN_DARK_HOVER = "#2a3040"

STEP_NAMES = ["Video", "Format", "Clips", "Captions", "Review"]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(APP_TITLE)
        self.configure(fg_color=BG_DARK)

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1200, sw - 40), min(800, sh - 80)
        self.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 2 - 20)))
        self.minsize(1040, 680)

        self.logq = queue.Queue()
        self.busy = False
        self.vo_path = ""
        self.installing = False
        self.current_step = 0
        self.current_view = "Create"

        # Wizard state variables
        self.format_val = "Vertical 9:16"
        self.framing_val = "Smart"
        self.speed_val = 1.0
        self.clipping_mode_val = "Quality"
        self.clip_length_val = "30-60s"
        self.caption_style_val = "Pop"
        self.caption_pacing_val = "Fast (2-3 words)"
        self.caption_pos_val = "Bottom (Reels safe)"
        self.caption_font_val = "Impact"

        self._build_shell()
        self._set_view("Create")
        self.after(100, self._drain)
        self.after(700, self._auto_offer)
        self.bind("<Control-j>", lambda e: self.start())

    def report_callback_exception(self, exc, val, tb):
        self.log("UI ERROR: %r" % (val,))

    # ----------------------------------------------------------------------
    # Shell: Sidebar + Content Area
    # ----------------------------------------------------------------------
    def _build_shell(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 1. Left Sidebar
        self.sidebar = ctk.CTkFrame(self, width=210, fg_color=SIDEBAR_BG, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        # Logo row
        logo_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_row.pack(fill="x", padx=16, pady=(18, 16))
        ctk.CTkLabel(logo_row, text="⚡", font=ctk.CTkFont(size=20), text_color="#f59e0b").pack(side="left")
        ctk.CTkLabel(logo_row, text=" BridgeClip", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=TEXT_MAIN).pack(side="left")

        # Studio Section
        ctk.CTkLabel(self.sidebar, text="STUDIO", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=16, pady=(8, 4))
        self.nav_btns = {}
        for name, icon in [("Create", "🪄"), ("Library", "📁"), ("Jobs", "📋")]:
            btn = ctk.CTkButton(self.sidebar, text="  " + icon + "  " + name, anchor="w",
                                height=38, corner_radius=8, font=ctk.CTkFont(size=13, weight="bold"),
                                fg_color="transparent", hover_color=BTN_DARK_HOVER,
                                text_color=TEXT_MUTED, command=lambda n=name: self._set_view(n))
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_btns[name] = btn

        # Workspace Section
        ctk.CTkLabel(self.sidebar, text="WORKSPACE", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=16, pady=(18, 4))
        for name, icon in [("Settings", "⚙️")]:
            btn = ctk.CTkButton(self.sidebar, text="  " + icon + "  " + name, anchor="w",
                                height=38, corner_radius=8, font=ctk.CTkFont(size=13, weight="bold"),
                                fg_color="transparent", hover_color=BTN_DARK_HOVER,
                                text_color=TEXT_MUTED, command=lambda n=name: self._set_view(n))
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_btns[name] = btn

        # Sidebar Footer
        sb_footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        sb_footer.pack(side="bottom", fill="x", padx=16, pady=16)
        status_row = ctk.CTkFrame(sb_footer, fg_color="transparent")
        status_row.pack(fill="x")
        self.sb_dot = ctk.CTkLabel(status_row, text="●", font=ctk.CTkFont(size=14), text_color=ACCENT_GREEN)
        self.sb_dot.pack(side="left")
        self.sb_status = ctk.CTkLabel(status_row, text=" Ready to clip", font=ctk.CTkFont(size=12),
                                      text_color=TEXT_MUTED)
        self.sb_status.pack(side="left")
        ctk.CTkLabel(sb_footer, text="v0.1.20", font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
                     anchor="w").pack(fill="x", pady=(2, 0))

        # 2. Main Content Host
        self.main_host = ctk.CTkFrame(self, fg_color=BG_DARK, corner_radius=0)
        self.main_host.grid(row=0, column=1, sticky="nsew", padx=20, pady=16)
        self.main_host.grid_columnconfigure(0, weight=1)
        self.main_host.grid_rowconfigure(1, weight=1)

        # Build view pages
        self._build_create_view()
        self._build_jobs_view()
        self._build_settings_view()
        self._build_library_view()

    def _set_view(self, name):
        self.current_view = name
        for n, btn in self.nav_btns.items():
            if n == name:
                btn.configure(fg_color="#1e2433", text_color="#38bdf8")
            else:
                btn.configure(fg_color="transparent", text_color=TEXT_MUTED)

        for v in (self.view_create, self.view_jobs, self.view_settings, self.view_library):
            v.grid_forget()

        if name == "Create":
            self.view_create.grid(row=0, column=0, sticky="nsew")
        elif name == "Jobs":
            self.view_jobs.grid(row=0, column=0, sticky="nsew")
        elif name == "Settings":
            self.view_settings.grid(row=0, column=0, sticky="nsew")
        elif name == "Library":
            self.view_library.grid(row=0, column=0, sticky="nsew")
            self._refresh_library_list()

    # ----------------------------------------------------------------------
    # View 1: Studio Create Wizard
    # ----------------------------------------------------------------------
    def _build_create_view(self):
        self.view_create = ctk.CTkFrame(self.main_host, fg_color="transparent")
        self.view_create.grid_columnconfigure(0, weight=1)
        self.view_create.grid_rowconfigure(2, weight=1)

        # Header
        top_header = ctk.CTkFrame(self.view_create, fg_color="transparent")
        top_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(top_header, text="STUDIO", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x")
        ctk.CTkLabel(top_header, text="Create clips", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(top_header,
                     text="Pick a long video and a few options. BridgeClip finds the strongest moments and cuts them into captioned clips.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x")

        # Stepper bar
        self.stepper_frame = ctk.CTkFrame(self.view_create, fg_color="transparent")
        self.stepper_frame.grid(row=1, column=0, sticky="ew", pady=(12, 16))
        self.step_indicators = []
        for i, name in enumerate(STEP_NAMES):
            step_btn = ctk.CTkButton(self.stepper_frame, text="%d  %s" % (i + 1, name),
                                     height=30, corner_radius=15, font=ctk.CTkFont(size=12, weight="bold"),
                                     fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, text_color=TEXT_MUTED,
                                     command=lambda s=i: self._set_step(s))
            step_btn.pack(side="left", padx=(0, 10))
            self.step_indicators.append(step_btn)

        # Step Cards Container
        self.step_container = ctk.CTkFrame(self.view_create, fg_color=CARD_BG, corner_radius=14,
                                           border_width=1, border_color=CARD_BORDER)
        self.step_container.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        self.step_container.grid_columnconfigure(0, weight=1)
        self.step_container.grid_rowconfigure(0, weight=1)

        # Build each wizard step card
        self._build_step_video()
        self._build_step_format()
        self._build_step_clips()
        self._build_step_captions()
        self._build_step_review()

        # Bottom Action Bar
        self.bot_bar = ctk.CTkFrame(self.view_create, fg_color="transparent")
        self.bot_bar.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        self.btn_back = ctk.CTkButton(self.bot_bar, text="← Back", width=100, height=40,
                                      corner_radius=8, fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER,
                                      font=ctk.CTkFont(size=13, weight="bold"), command=self._prev_step)
        self.btn_back.pack(side="left")

        self.hint_label = ctk.CTkLabel(self.bot_bar, text="Ctrl+J generates from any step",
                                       font=ctk.CTkFont(size=12), text_color=TEXT_DIM)
        self.hint_label.pack(side="left", padx=20)

        self.btn_generate_now = ctk.CTkButton(self.bot_bar, text="Generate now", width=120, height=40,
                                              corner_radius=8, fg_color="transparent", hover_color=BTN_DARK_HOVER,
                                              text_color=TEXT_MUTED, font=ctk.CTkFont(size=13),
                                              command=self.start)
        self.btn_generate_now.pack(side="right", padx=(8, 0))

        self.btn_next = ctk.CTkButton(self.bot_bar, text="Next: Format →", width=150, height=40,
                                      corner_radius=8, fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER,
                                      font=ctk.CTkFont(size=13, weight="bold"), command=self._next_step)
        self.btn_next.pack(side="right")

    def _set_step(self, idx):
        self.current_step = max(0, min(4, idx))
        for i, ind in enumerate(self.step_indicators):
            if i < self.current_step:
                ind.configure(fg_color="#1e293b", text_color="#38bdf8", text="✓  %s" % STEP_NAMES[i])
            elif i == self.current_step:
                ind.configure(fg_color=ACCENT_BLUE, text_color="#ffffff", text="%d  %s" % (i + 1, STEP_NAMES[i]))
            else:
                ind.configure(fg_color=BTN_DARK, text_color=TEXT_MUTED, text="%d  %s" % (i + 1, STEP_NAMES[i]))

        for page in (self.page_video, self.page_format, self.page_clips, self.page_captions, self.page_review):
            page.grid_forget()

        pages = [self.page_video, self.page_format, self.page_clips, self.page_captions, self.page_review]
        pages[self.current_step].grid(row=0, column=0, sticky="nsew", padx=24, pady=20)

        if self.current_step == 0:
            self.btn_back.configure(state="disabled")
        else:
            self.btn_back.configure(state="normal")

        next_labels = ["Next: Format →", "Next: Clips →", "Next: Captions →", "Next: Review →", "✨ Generate clips"]
        self.btn_next.configure(text=next_labels[self.current_step])
        if self.current_step == 4:
            self.btn_next.configure(fg_color="#3b82f6", hover_color="#2563eb", width=160)
            self._update_review_page()
        else:
            self.btn_next.configure(fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, width=150)

    def _next_step(self):
        if self.current_step == 4:
            self.start()
        else:
            self._set_step(self.current_step + 1)

    def _prev_step(self):
        if self.current_step > 0:
            self._set_step(self.current_step - 1)

    # ----------------------------------------------------------------------
    # Step 1: Video
    # ----------------------------------------------------------------------
    def _build_step_video(self):
        self.page_video = ctk.CTkFrame(self.step_container, fg_color="transparent")
        self.page_video.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_video, text="Choose a video", font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_video,
                     text="A local file, YouTube link or direct video link. Optionally clip only part of it.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 16))

        # Drop Box Card
        drop_box = ctk.CTkFrame(self.page_video, fg_color="#12151d", corner_radius=12,
                                border_width=1, border_color="#222736")
        drop_box.pack(fill="x", pady=(0, 16), ipady=10)

        ctk.CTkLabel(drop_box, text="📥  Add a long video", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_MAIN).pack(pady=(12, 2))
        ctk.CTkLabel(drop_box, text="Drop a video file or link here, or paste a link below.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM).pack(pady=(0, 8))

        badges_row = ctk.CTkFrame(drop_box, fg_color="transparent")
        badges_row.pack(pady=(0, 10))
        for b in ["▶ YouTube", "👾 Twitch VODs", "📁 Local MP4/MKV"]:
            ctk.CTkLabel(badges_row, text=b, font=ctk.CTkFont(size=11), text_color=TEXT_MUTED,
                         fg_color="#1e2330", corner_radius=6, padx=8, pady=3).pack(side="left", padx=4)

        input_row = ctk.CTkFrame(drop_box, fg_color="transparent")
        input_row.pack(fill="x", padx=18, pady=(4, 10))
        self.src = ctk.CTkEntry(input_row, height=42, corner_radius=8,
                                placeholder_text="YouTube, Twitch VOD or direct video link (or path)",
                                fg_color="#181c26", border_color="#2a3142")
        self.src.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.src.bind("<KeyRelease>", lambda e: self._on_src_changed())

        ctk.CTkButton(input_row, text="📁 Browse", width=95, height=42, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER,
                      font=ctk.CTkFont(size=13, weight="bold"), command=self.pick_file).pack(side="right")

        # Preview card of selected video
        self.selected_card = ctk.CTkFrame(self.page_video, fg_color="#172236", corner_radius=10,
                                          border_width=1, border_color="#3b82f6")
        card_inner = ctk.CTkFrame(self.selected_card, fg_color="transparent")
        card_inner.pack(fill="x", padx=14, pady=10)
        self.sel_thumb = ctk.CTkLabel(card_inner, text="🎬", font=ctk.CTkFont(size=24))
        self.sel_thumb.pack(side="left", padx=(0, 10))
        self.sel_title = ctk.CTkLabel(card_inner, text="Ready to clip", font=ctk.CTkFont(size=13, weight="bold"),
                                      text_color=TEXT_MAIN, anchor="w")
        self.sel_title.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(card_inner, text="Replace", width=70, height=28, corner_radius=6,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=11),
                      command=self.pick_file).pack(side="right", padx=(6, 0))

        # Part Range Card
        range_card = ctk.CTkFrame(self.page_video, fg_color="#12151d", corner_radius=10,
                                  border_width=1, border_color="#222736")
        range_card.pack(fill="x", pady=(0, 14), padx=0)
        rtop = ctk.CTkFrame(range_card, fg_color="transparent")
        rtop.pack(fill="x", padx=16, pady=(10, 4))
        ctk.CTkLabel(rtop, text="Clip only part of the video", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT_MAIN).pack(side="left")
        self.range_switch = ctk.CTkSwitch(rtop, text="")
        self.range_switch.pack(side="right")

        ctk.CTkLabel(range_card, text="Set a start and end time. Leave either empty for an open range.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=16, pady=(0, 8))

        # Quality Row
        qrow = ctk.CTkFrame(self.page_video, fg_color="transparent")
        qrow.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(qrow, text="YouTube download quality:", font=ctk.CTkFont(size=13),
                     text_color=TEXT_MUTED).pack(side="left")
        self.dl_quality = ctk.CTkOptionMenu(
            qrow, width=200, height=32, corner_radius=6,
            values=["Maximum (4K/1440p/Best)", "1080p Full HD (Crisp)", "720p HD", "Auto / Fast"],
            fg_color="#1b202c", button_color="#242b3b")
        self.dl_quality.set("1080p Full HD (Crisp)")
        self.dl_quality.pack(side="right")

    def _on_src_changed(self):
        val = self.src.get().strip()
        if val:
            name = os.path.basename(val) if os.path.isfile(val) else val
            self.sel_title.configure(text=name[:65] + ("..." if len(name) > 65 else ""))
            self.selected_card.pack(fill="x", pady=(0, 14), before=self.page_video.winfo_children()[-2])
        else:
            self.selected_card.pack_forget()

    # ----------------------------------------------------------------------
    # Step 2: Format
    # ----------------------------------------------------------------------
    def _build_step_format(self):
        self.page_format = ctk.CTkScrollableFrame(self.step_container, fg_color="transparent")
        self.page_format.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_format, text="Format, framing and speed",
                     font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_format, text="Choose the look and pace of every clip in this job.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 14))

        # 1. Format cards (Vertical 9:16 vs Horizontal 16:9)
        ctk.CTkLabel(self.page_format, text="FORMAT", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 4))
        fmt_row = ctk.CTkFrame(self.page_format, fg_color="transparent")
        fmt_row.pack(fill="x", pady=(0, 12))
        fmt_row.columnconfigure((0, 1), weight=1)

        self.fmt_cards = {}
        for idx, (title, sub, icon) in enumerate([
            ("Vertical 9:16", "Shorts, Reels, TikTok", "📱"),
            ("Horizontal 16:9", "YouTube, X, LinkedIn", "🖥️"),
        ]):
            card = ctk.CTkFrame(fmt_row, fg_color=CARD_ACTIVE_BG if idx == 0 else "#12151d",
                                corner_radius=10, border_width=1,
                                border_color=CARD_ACTIVE_BORDER if idx == 0 else CARD_BORDER,
                                cursor="hand2")
            card.grid(row=0, column=idx, sticky="ew", padx=4)
            card.bind("<Button-1>", lambda e, t=title: self._select_format(t))

            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=12)
            r.bind("<Button-1>", lambda e, t=title: self._select_format(t))

            l1 = ctk.CTkLabel(r, text=icon + "  " + title, font=ctk.CTkFont(size=14, weight="bold"),
                              text_color=TEXT_MAIN)
            l1.pack(anchor="w")
            l1.bind("<Button-1>", lambda e, t=title: self._select_format(t))

            l2 = ctk.CTkLabel(r, text=sub, font=ctk.CTkFont(size=11), text_color=TEXT_DIM)
            l2.pack(anchor="w", pady=(2, 0))
            l2.bind("<Button-1>", lambda e, t=title: self._select_format(t))

            self.fmt_cards[title] = card

        # 2. Framing cards
        ctk.CTkLabel(self.page_format, text="FRAMING", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        frm_row = ctk.CTkFrame(self.page_format, fg_color="transparent")
        frm_row.pack(fill="x", pady=(0, 10))
        frm_row.columnconfigure((0, 1, 2), weight=1)

        self.framing_cards = {}
        for idx, (title, sub) in enumerate([
            ("Smart", "Auto frames each shot"),
            ("Full frame", "Follows the speaker"),
            ("Classic", "Whole frame, blurred"),
        ]):
            card = ctk.CTkFrame(frm_row, fg_color=CARD_ACTIVE_BG if idx == 0 else "#12151d",
                                corner_radius=10, border_width=1,
                                border_color=CARD_ACTIVE_BORDER if idx == 0 else CARD_BORDER,
                                cursor="hand2")
            card.grid(row=0, column=idx, sticky="ew", padx=4)
            card.bind("<Button-1>", lambda e, t=title: self._select_framing(t))

            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=10)
            r.bind("<Button-1>", lambda e, t=title: self._select_framing(t))

            l1 = ctk.CTkLabel(r, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_MAIN)
            l1.pack(anchor="w")
            l1.bind("<Button-1>", lambda e, t=title: self._select_framing(t))

            l2 = ctk.CTkLabel(r, text=sub, font=ctk.CTkFont(size=11), text_color=TEXT_DIM)
            l2.pack(anchor="w", pady=(2, 0))
            l2.bind("<Button-1>", lambda e, t=title: self._select_framing(t))

            self.framing_cards[title] = card

        # 3. Pacing switch (Cut dead air)
        ctk.CTkLabel(self.page_format, text="PACING", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        pacing_card = ctk.CTkFrame(self.page_format, fg_color="#12151d", corner_radius=10,
                                   border_width=1, border_color=CARD_BORDER)
        pacing_card.pack(fill="x", pady=(0, 10))
        pinner = ctk.CTkFrame(pacing_card, fg_color="transparent")
        pinner.pack(fill="x", padx=14, pady=10)
        ptext = ctk.CTkFrame(pinner, fg_color="transparent")
        ptext.pack(side="left")
        ctk.CTkLabel(ptext, text="Cut dead air", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_MAIN).pack(anchor="w")
        ctk.CTkLabel(ptext, text="Trims long pauses and filler words, keeps demos.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(anchor="w")
        self.snap = ctk.CTkSwitch(pinner, text="")
        self.snap.select()
        self.snap.pack(side="right")

        # 4. Video Speed
        ctk.CTkLabel(self.page_format, text="VIDEO SPEED", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        spd_row = ctk.CTkFrame(self.page_format, fg_color="transparent")
        spd_row.pack(fill="x", pady=(0, 4))
        spd_row.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        self.speed_btns = {}
        speeds = [(1.0, "1x\nNormal"), (1.1, "1.1x\n55s/m"), (1.25, "1.25x\n48s/m"),
                  (1.5, "1.5x\n40s/m"), (1.75, "1.75x\n34s/m"), (2.0, "2x\n30s/m")]
        for idx, (spd, lbl) in enumerate(speeds):
            btn = ctk.CTkButton(spd_row, text=lbl, height=44, corner_radius=8,
                                font=ctk.CTkFont(size=11, weight="bold"),
                                fg_color=CARD_ACTIVE_BG if idx == 0 else "#12151d",
                                border_width=1, border_color=CARD_ACTIVE_BORDER if idx == 0 else CARD_BORDER,
                                text_color=TEXT_MAIN, command=lambda s=spd: self._select_speed(s))
            btn.grid(row=0, column=idx, sticky="ew", padx=3)
            self.speed_btns[spd] = btn

        ctk.CTkLabel(self.page_format,
                     text="Speeds up every exported clip, keeping voice pitch natural and captions in sync. Faster clips are shorter.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 0))

    def _select_format(self, val):
        self.format_val = val
        for title, card in self.fmt_cards.items():
            if title == val:
                card.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                card.configure(fg_color="#12151d", border_color=CARD_BORDER)

    def _select_framing(self, val):
        self.framing_val = val
        for title, card in self.framing_cards.items():
            if title == val:
                card.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                card.configure(fg_color="#12151d", border_color=CARD_BORDER)

    def _select_speed(self, spd):
        self.speed_val = spd
        for s, btn in self.speed_btns.items():
            if s == spd:
                btn.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                btn.configure(fg_color="#12151d", border_color=CARD_BORDER)

    # ----------------------------------------------------------------------
    # Step 3: Clips
    # ----------------------------------------------------------------------
    def _build_step_clips(self):
        self.page_clips = ctk.CTkScrollableFrame(self.step_container, fg_color="transparent")
        self.page_clips.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_clips, text="Clip length and count",
                     font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_clips, text="Pick one or more lengths, or leave them all off for any length.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 14))

        # 1. Clipping Mode cards
        ctk.CTkLabel(self.page_clips, text="CLIPPING MODE", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 4))
        mode_row = ctk.CTkFrame(self.page_clips, fg_color="transparent")
        mode_row.pack(fill="x", pady=(0, 12))
        mode_row.columnconfigure((0, 1, 2), weight=1)

        self.mode_cards = {}
        for idx, (title, sub) in enumerate([
            ("Quality", "Opus / Local LLM planning"),
            ("Economy", "Replay Heatmap / Fast"),
            ("Direct", "Peak Energy (Loudest moments)"),
        ]):
            card = ctk.CTkFrame(mode_row, fg_color=CARD_ACTIVE_BG if idx == 0 else "#12151d",
                                corner_radius=10, border_width=1,
                                border_color=CARD_ACTIVE_BORDER if idx == 0 else CARD_BORDER,
                                cursor="hand2")
            card.grid(row=0, column=idx, sticky="ew", padx=4)
            card.bind("<Button-1>", lambda e, t=title: self._select_clipping_mode(t))

            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=10)
            r.bind("<Button-1>", lambda e, t=title: self._select_clipping_mode(t))

            l1 = ctk.CTkLabel(r, text=title, font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_MAIN)
            l1.pack(anchor="w")
            l1.bind("<Button-1>", lambda e, t=title: self._select_clipping_mode(t))

            l2 = ctk.CTkLabel(r, text=sub, font=ctk.CTkFont(size=11), text_color=TEXT_DIM)
            l2.pack(anchor="w", pady=(2, 0))
            l2.bind("<Button-1>", lambda e, t=title: self._select_clipping_mode(t))

            self.mode_cards[title] = card

        # 2. Clip Length
        ctk.CTkLabel(self.page_clips, text="CLIP LENGTH", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        len_row = ctk.CTkFrame(self.page_clips, fg_color="transparent")
        len_row.pack(fill="x", pady=(0, 12))
        len_row.columnconfigure((0, 1, 2, 3, 4, 5, 6), weight=1)

        self.len_btns = {}
        lengths = [
            ("10-30s", "Extra short"),
            ("30-60s", "Short"),
            ("1-2m", "Medium"),
            ("2-5m", "Long"),
            ("5-10m", "Extra long"),
            ("10-15m", "Extended"),
            ("15-30m", "Feature"),
        ]
        for idx, (dur, sub) in enumerate(lengths):
            btn = ctk.CTkButton(len_row, text=dur + "\n" + sub, height=48, corner_radius=8,
                                font=ctk.CTkFont(size=11, weight="bold"),
                                fg_color=CARD_ACTIVE_BG if idx == 1 else "#12151d",
                                border_width=1, border_color=CARD_ACTIVE_BORDER if idx == 1 else CARD_BORDER,
                                text_color=TEXT_MAIN, command=lambda d=dur: self._select_clip_length(d))
            btn.grid(row=0, column=idx, sticky="ew", padx=2)
            self.len_btns[dur] = btn

        # 3. Number of Clips
        ctk.CTkLabel(self.page_clips, text="NUMBER OF CLIPS", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 4))
        count_card = ctk.CTkFrame(self.page_clips, fg_color="#12151d", corner_radius=10,
                                  border_width=1, border_color=CARD_BORDER)
        count_card.pack(fill="x", pady=(0, 10))
        cinner = ctk.CTkFrame(count_card, fg_color="transparent")
        cinner.pack(fill="x", padx=14, pady=10)
        ctext = ctk.CTkFrame(cinner, fg_color="transparent")
        ctext.pack(side="left")
        ctk.CTkLabel(ctext, text="Let AI decide", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_MAIN).pack(anchor="w")
        ctk.CTkLabel(ctext, text="Every moment worth posting.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(anchor="w")
        self.ai_decide_switch = ctk.CTkSwitch(cinner, text="", command=self._toggle_ai_count)
        self.ai_decide_switch.select()
        self.ai_decide_switch.pack(side="right")

        self.custom_count_row = ctk.CTkFrame(count_card, fg_color="transparent")
        ctk.CTkLabel(self.custom_count_row, text="Exact max clips:", font=ctk.CTkFont(size=12),
                     text_color=TEXT_MUTED).pack(side="left", padx=(14, 8))
        self.max_clips_entry = ctk.CTkEntry(self.custom_count_row, width=80, height=30)
        self.max_clips_entry.insert(0, "3")
        self.max_clips_entry.pack(side="left", pady=(0, 8))

    def _select_clipping_mode(self, val):
        self.clipping_mode_val = val
        for title, card in self.mode_cards.items():
            if title == val:
                card.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                card.configure(fg_color="#12151d", border_color=CARD_BORDER)

    def _select_clip_length(self, val):
        self.clip_length_val = val
        for dur, btn in self.len_btns.items():
            if dur == val:
                btn.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
            else:
                btn.configure(fg_color="#12151d", border_color=CARD_BORDER)

    def _toggle_ai_count(self):
        if self.ai_decide_switch.get():
            self.custom_count_row.pack_forget()
        else:
            self.custom_count_row.pack(fill="x", padx=14, pady=(0, 8))

    # ----------------------------------------------------------------------
    # Step 4: Captions
    # ----------------------------------------------------------------------
    def _build_step_captions(self):
        self.page_captions = ctk.CTkScrollableFrame(self.step_container, fg_color="transparent")
        self.page_captions.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_captions, text="Captions",
                     font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_captions, text="Word-by-word captions burned into each clip. Silent videos are clipped without them.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 10))

        # Top toggles card
        top_c = ctk.CTkFrame(self.page_captions, fg_color="#12151d", corner_radius=10,
                             border_width=1, border_color=CARD_BORDER)
        top_c.pack(fill="x", pady=(0, 12))
        tc_inner = ctk.CTkFrame(top_c, fg_color="transparent")
        tc_inner.pack(fill="x", padx=14, pady=10)

        t_left = ctk.CTkFrame(tc_inner, fg_color="transparent")
        t_left.pack(side="left")
        ctk.CTkLabel(t_left, text="Burn in captions", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=TEXT_MAIN).pack(anchor="w")
        ctk.CTkLabel(t_left, text="Turn off for clean clips without on-screen text.",
                     font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(anchor="w")

        self.captions_switch = ctk.CTkSwitch(tc_inner, text="")
        self.captions_switch.select()
        self.captions_switch.pack(side="right")

        # 12 Visual Style Preset Cards (2 rows of 6)
        ctk.CTkLabel(self.page_captions, text="CAPTION STYLE PRESETS", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 6))

        grid_frame = ctk.CTkFrame(self.page_captions, fg_color="transparent")
        grid_frame.pack(fill="x", pady=(0, 12))
        for col in range(6):
            grid_frame.columnconfigure(col, weight=1)

        self.caption_cards = {}
        preset_names = ["Pop", "Spotlight", "Impact", "Glow", "Boxed", "Sweep",
                        "Editorial", "Hype", "Punch", "Neon", "Headline", "Subtle"]

        for idx, name in enumerate(preset_names):
            row = idx // 6
            col = idx % 6
            info = CAPTION_STYLES.get(name, {})

            card = ctk.CTkFrame(grid_frame, fg_color=CARD_ACTIVE_BG if name == "Pop" else "#12151d",
                                corner_radius=10, border_width=1,
                                border_color=CARD_ACTIVE_BORDER if name == "Pop" else CARD_BORDER,
                                height=85, cursor="hand2")
            card.grid(row=row, column=col, sticky="nsew", padx=3, pady=4)
            card.grid_propagate(False)
            card.bind("<Button-1>", lambda e, n=name: self._select_caption_style(n))

            # Sample text preview box
            sample_box = ctk.CTkFrame(card, fg_color=info.get("sample_bg", "#181b22"), corner_radius=6)
            sample_box.pack(fill="both", expand=True, padx=6, pady=(6, 2))
            sample_box.bind("<Button-1>", lambda e, n=name: self._select_caption_style(n))

            s_lbl = ctk.CTkLabel(sample_box, text=info.get("sample", name),
                                 font=ctk.CTkFont(family="Arial Black" if info.get("font") != "Georgia" else "Georgia",
                                                  size=10, weight="bold"),
                                 text_color=info.get("sample_color", "#ffffff"))
            s_lbl.pack(expand=True)
            s_lbl.bind("<Button-1>", lambda e, n=name: self._select_caption_style(n))

            # Bottom name label
            n_lbl = ctk.CTkLabel(card, text=name, font=ctk.CTkFont(size=11, weight="bold"),
                                 text_color=TEXT_MAIN if name == "Pop" else TEXT_MUTED)
            n_lbl.pack(pady=(0, 4))
            n_lbl.bind("<Button-1>", lambda e, n=name: self._select_caption_style(n))

            self.caption_cards[name] = (card, n_lbl)

        # Options Row (Pacing, Position, Size, Language)
        opt_card = ctk.CTkFrame(self.page_captions, fg_color="#12151d", corner_radius=10,
                                border_width=1, border_color=CARD_BORDER)
        opt_card.pack(fill="x", pady=(2, 6))
        opt_card.columnconfigure((0, 1, 2, 3), weight=1)

        # Pacing
        c1 = ctk.CTkFrame(opt_card, fg_color="transparent")
        c1.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(c1, text="Pacing (words)", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM).pack(anchor="w")
        self.cap_pacing = ctk.CTkOptionMenu(
            c1, height=30, values=["Punchy (1-2 words)", "Fast (2-3 words)", "Balanced (3-4 words)", "Sentence (5-7)"],
            fg_color="#1a1f2b", button_color="#242b3b")
        self.cap_pacing.set("Fast (2-3 words)")
        self.cap_pacing.pack(fill="x", pady=(4, 0))

        # Position
        c2 = ctk.CTkFrame(opt_card, fg_color="transparent")
        c2.grid(row=0, column=1, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(c2, text="Position", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM).pack(anchor="w")
        self.cap_pos = ctk.CTkOptionMenu(
            c2, height=30, values=["Bottom (Reels safe)", "Center (Focus)", "Bottom Low"],
            fg_color="#1a1f2b", button_color="#242b3b")
        self.cap_pos.set("Bottom (Reels safe)")
        self.cap_pos.pack(fill="x", pady=(4, 0))

        # Size
        c3 = ctk.CTkFrame(opt_card, fg_color="transparent")
        c3.grid(row=0, column=2, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(c3, text="Caption Size", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM).pack(anchor="w")
        self.cap_size = ctk.CTkSegmentedButton(
            c3, height=30, values=["S", "M", "L", "XL"])
        self.cap_size.set("M")
        self.cap_size.pack(fill="x", pady=(4, 0))

        # Language
        c4 = ctk.CTkFrame(opt_card, fg_color="transparent")
        c4.grid(row=0, column=3, sticky="ew", padx=10, pady=10)
        ctk.CTkLabel(c4, text="Language", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM).pack(anchor="w")
        self.cap_lang = ctk.CTkOptionMenu(
            c4, height=30, values=list(CAPTION_LANGS.keys()),
            fg_color="#1a1f2b", button_color="#242b3b")
        self.cap_lang.pack(fill="x", pady=(4, 0))

    def _select_caption_style(self, val):
        self.caption_style_val = val
        for name, (card, n_lbl) in self.caption_cards.items():
            if name == val:
                card.configure(fg_color=CARD_ACTIVE_BG, border_color=CARD_ACTIVE_BORDER)
                n_lbl.configure(text_color=TEXT_MAIN)
            else:
                card.configure(fg_color="#12151d", border_color=CARD_BORDER)
                n_lbl.configure(text_color=TEXT_MUTED)

    # ----------------------------------------------------------------------
    # Step 5: Review
    # ----------------------------------------------------------------------
    def _build_step_review(self):
        self.page_review = ctk.CTkScrollableFrame(self.step_container, fg_color="transparent")
        self.page_review.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.page_review, text="Review and generate",
                     font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.page_review, text="Check the run, then generate. You can queue another video right after.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(2, 14))

        self.review_table = ctk.CTkFrame(self.page_review, fg_color="#12151d", corner_radius=12,
                                         border_width=1, border_color=CARD_BORDER)
        self.review_table.pack(fill="x", pady=(0, 14))

        self.review_rows = {}
        fields = [
            ("Video", 0),
            ("Format", 1),
            ("Pacing", 1),
            ("Speed", 1),
            ("Mode", 2),
            ("Clips", 2),
            ("Captions", 3),
        ]
        for idx, (label, target_step) in enumerate(fields):
            row = ctk.CTkFrame(self.review_table, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=8)

            ctk.CTkLabel(row, text=label, width=90, font=ctk.CTkFont(size=13),
                         text_color=TEXT_DIM, anchor="w").pack(side="left")

            val_lbl = ctk.CTkLabel(row, text="--", font=ctk.CTkFont(size=13, weight="bold"),
                                   text_color=TEXT_MAIN, anchor="w")
            val_lbl.pack(side="left", fill="x", expand=True)

            ctk.CTkButton(row, text="Edit", width=55, height=26, corner_radius=6,
                          fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=11),
                          command=lambda s=target_step: self._set_step(s)).pack(side="right")

            if idx < len(fields) - 1:
                sep = ctk.CTkFrame(self.review_table, height=1, fg_color="#1d222e")
                sep.pack(fill="x", padx=14)

            self.review_rows[label] = val_lbl

        ctk.CTkLabel(self.page_review,
                     text="⏱️ Runs on this computer. Local AI model & Whisper used for transcription and hype planning.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(6, 0))

    def _update_review_page(self):
        src_val = self.src.get().strip()
        disp_src = os.path.basename(src_val) if os.path.isfile(src_val) else (src_val or "No video specified")
        self.review_rows["Video"].configure(text=disp_src[:50] + ("..." if len(disp_src) > 50 else ""))

        self.review_rows["Format"].configure(text="%s · %s framing" % (self.format_val, self.framing_val))
        self.review_rows["Pacing"].configure(text="Cut dead air" if self.snap.get() else "Natural timing")
        self.review_rows["Speed"].configure(text="%.2gx · %s" % (self.speed_val, "Normal" if self.speed_val == 1.0 else "Sped up"))
        self.review_rows["Mode"].configure(text="%s · AI Planning" % self.clipping_mode_val)

        clip_str = "%s · %s" % (self.clip_length_val, "AI decides count" if self.ai_decide_switch.get() else ("Max %s clips" % self.max_clips_entry.get()))
        self.review_rows["Clips"].configure(text=clip_str)

        cap_str = "%s (Viral)" % self.caption_style_val if self.captions_switch.get() else "Off"
        self.review_rows["Captions"].configure(text=cap_str)

    # ----------------------------------------------------------------------
    # View 2: Jobs
    # ----------------------------------------------------------------------
    def _build_jobs_view(self):
        self.view_jobs = ctk.CTkFrame(self.main_host, fg_color="transparent")
        self.view_jobs.grid_columnconfigure(0, weight=1)
        self.view_jobs.grid_rowconfigure(2, weight=1)

        # Header
        top_h = ctk.CTkFrame(self.view_jobs, fg_color="transparent")
        top_h.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(top_h, text="STUDIO", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x")
        ctk.CTkLabel(top_h, text="Jobs & Progress", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x", pady=(2, 2))

        # Status banner card
        stat_card = ctk.CTkFrame(self.view_jobs, fg_color=CARD_BG, corner_radius=12,
                                 border_width=1, border_color=CARD_BORDER)
        stat_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        sc_inner = ctk.CTkFrame(stat_card, fg_color="transparent")
        sc_inner.pack(fill="x", padx=16, pady=12)

        self.jobs_status_lbl = ctk.CTkLabel(sc_inner, text="Idle - No active job",
                                            font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT_MAIN, anchor="w")
        self.jobs_status_lbl.pack(fill="x")

        self.progress = ctk.CTkProgressBar(sc_inner, mode="indeterminate", height=6, corner_radius=3,
                                           progress_color=ACCENT_BLUE)
        self.progress.pack(fill="x", pady=(8, 2))
        self.progress.set(0)

        # Console Log Textbox Card
        console_card = ctk.CTkFrame(self.view_jobs, fg_color=CARD_BG, corner_radius=12,
                                    border_width=1, border_color=CARD_BORDER)
        console_card.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        console_card.grid_columnconfigure(0, weight=1)
        console_card.grid_rowconfigure(0, weight=1)

        self.console = ctk.CTkTextbox(console_card, font=ctk.CTkFont(family="Consolas", size=12),
                                      fg_color="#0e1117", text_color="#cbd5e1", corner_radius=10, wrap="word")
        self.console.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.console.configure(state="disabled")

        # Bottom buttons
        j_btns = ctk.CTkFrame(self.view_jobs, fg_color="transparent")
        j_btns.grid(row=3, column=0, sticky="ew")

        ctk.CTkButton(j_btns, text="📁 Open Output Folder", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=self.open_out).pack(side="left", padx=(0, 8))

        ctk.CTkButton(j_btns, text="📁 Open Videos Folder", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=self.open_videos).pack(side="left", padx=8)

        ctk.CTkButton(j_btns, text="Clear Log", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12),
                      command=self.clear_log).pack(side="left", padx=8)

        ctk.CTkButton(j_btns, text="🪄 Back to Create", height=38, corner_radius=8,
                      fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=lambda: self._set_view("Create")).pack(side="right")

    # ----------------------------------------------------------------------
    # View 3: Settings
    # ----------------------------------------------------------------------
    def _build_settings_view(self):
        self.view_settings = ctk.CTkScrollableFrame(self.main_host, fg_color="transparent")
        self.view_settings.grid_columnconfigure(0, weight=1)

        # Header
        ctk.CTkLabel(self.view_settings, text="PREFERENCES", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x")
        ctk.CTkLabel(self.view_settings, text="Settings", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(self.view_settings, text="Changes save automatically to hypeclipper_settings.json.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(0, 14))

        # 1. Status Banner Card
        stat_card = ctk.CTkFrame(self.view_settings, fg_color=CARD_BG, corner_radius=12,
                                 border_width=1, border_color=CARD_BORDER)
        stat_card.pack(fill="x", pady=(0, 14))
        sc_inner = ctk.CTkFrame(stat_card, fg_color="transparent")
        sc_inner.pack(fill="x", padx=16, pady=14)

        top_s = ctk.CTkFrame(sc_inner, fg_color="transparent")
        top_s.pack(fill="x")
        ctk.CTkLabel(top_s, text="✓  Ready to clip", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=ACCENT_GREEN).pack(side="left")
        ctk.CTkLabel(sc_inner, text="BridgeClip runs locally on this computer. Whisper and LLM cover transcription and clip selection.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(4, 10))

        pills_row = ctk.CTkFrame(sc_inner, fg_color="transparent")
        pills_row.pack(fill="x")
        pills_row.columnconfigure((0, 1, 2), weight=1)

        for col, (title, sub) in enumerate([
            ("● Local FreeLLMAPI", "Key saved"),
            ("● Core Tools", "ffmpeg, ffprobe, yt-dlp"),
            ("● Storage", "output_clips ready"),
        ]):
            p = ctk.CTkFrame(pills_row, fg_color="#12151d", corner_radius=8, border_width=1, border_color="#222736")
            p.grid(row=0, column=col, sticky="ew", padx=3)
            ctk.CTkLabel(p, text=title, font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_MAIN).pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(p, text=sub, font=ctk.CTkFont(size=11), text_color=TEXT_DIM).pack(anchor="w", padx=10, pady=(0, 6))

        # 2. API Keys Card
        api_card = ctk.CTkFrame(self.view_settings, fg_color=CARD_BG, corner_radius=12,
                                border_width=1, border_color=CARD_BORDER)
        api_card.pack(fill="x", pady=(0, 14))
        ac_inner = ctk.CTkFrame(api_card, fg_color="transparent")
        ac_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(ac_inner, text="🔑  API Configuration", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x")
        ctk.CTkLabel(ac_inner, text="OpenAI-compatible endpoint for Whisper transcription and clip picking.",
                     font=ctk.CTkFont(size=12), text_color=TEXT_DIM, anchor="w").pack(fill="x", pady=(2, 12))

        ctk.CTkLabel(ac_inner, text="API Base URL:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED, anchor="w").pack(fill="x")
        self.api = ctk.CTkEntry(ac_inner, height=38, corner_radius=8, fg_color="#12151d", border_color="#222736")
        self.api.insert(0, load_settings().get("api_url") or DEFAULT_API)
        self.api.pack(fill="x", pady=(2, 10))

        ctk.CTkLabel(ac_inner, text="API Key (FreeLLMAPI):", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED, anchor="w").pack(fill="x")
        self.api_key = ctk.CTkEntry(ac_inner, height=38, corner_radius=8, show="*",
                                    placeholder_text="freellmapi-...", fg_color="#12151d", border_color="#222736")
        if API_KEY:
            self.api_key.insert(0, API_KEY)
        self.api_key.pack(fill="x", pady=(2, 6))

        # 3. Tools Check & Install Card
        tools_card = ctk.CTkFrame(self.view_settings, fg_color=CARD_BG, corner_radius=12,
                                  border_width=1, border_color=CARD_BORDER)
        tools_card.pack(fill="x", pady=(0, 14))
        tc_inner = ctk.CTkFrame(tools_card, fg_color="transparent")
        tc_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(tc_inner, text="🛠️  Tools (ffmpeg, ffprobe, yt-dlp)", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x")

        t_btns = ctk.CTkFrame(tc_inner, fg_color="transparent")
        t_btns.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(t_btns, text="Install Missing Tools", height=34, corner_radius=8,
                      fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=self.install_clicked).pack(side="left", padx=(0, 8))
        ctk.CTkButton(t_btns, text="Update yt-dlp", height=34, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12),
                      command=self.update_ytdlp).pack(side="left", padx=8)
        ctk.CTkButton(t_btns, text="Check Tools", height=34, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12),
                      command=self.check_tools).pack(side="left", padx=8)

        # 4. Storage & Cookies Card
        store_card = ctk.CTkFrame(self.view_settings, fg_color=CARD_BG, corner_radius=12,
                                  border_width=1, border_color=CARD_BORDER)
        store_card.pack(fill="x", pady=(0, 14))
        st_inner = ctk.CTkFrame(store_card, fg_color="transparent")
        st_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(st_inner, text="📁  Storage & Cookies", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x")

        frow = ctk.CTkFrame(st_inner, fg_color="transparent")
        frow.pack(fill="x", pady=(8, 8))
        ctk.CTkLabel(frow, text="Downloads directory:", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_MUTED).pack(anchor="w")
        fin = ctk.CTkFrame(frow, fg_color="transparent")
        fin.pack(fill="x", pady=(2, 0))
        self.dl_dir = ctk.CTkEntry(fin, height=36, corner_radius=8, fg_color="#12151d", border_color="#222736")
        self.dl_dir.insert(0, VIDEOS_DIR)
        self.dl_dir.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(fin, text="Browse", width=80, height=36, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, command=self.pick_dl_dir).pack(side="right")

        crow = ctk.CTkFrame(st_inner, fg_color="transparent")
        crow.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(crow, text="Cookies from browser (for age-restricted/bot checks):",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.cookies = ctk.CTkOptionMenu(
            crow, height=34, corner_radius=8, values=["None", "chrome", "edge", "firefox", "brave"],
            fg_color="#12151d", button_color="#242b3b")
        self.cookies.pack(fill="x", pady=(2, 0))

        # Save Button
        ctk.CTkButton(self.view_settings, text="💾 Save Preferences", height=42, corner_radius=8,
                      fg_color=ACCENT_BLUE, hover_color=ACCENT_BLUE_HOVER, font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._save_preferences).pack(fill="x", pady=(6, 20))

    def _save_preferences(self):
        set_api_key(self.api_key.get())
        save_settings(api_url=self.api.get().strip() or DEFAULT_API, api_key=API_KEY)
        messagebox.showinfo(APP_TITLE, "Preferences saved successfully!")

    # ----------------------------------------------------------------------
    # View 4: Library
    # ----------------------------------------------------------------------
    def _build_library_view(self):
        self.view_library = ctk.CTkFrame(self.main_host, fg_color="transparent")
        self.view_library.grid_columnconfigure(0, weight=1)
        self.view_library.grid_rowconfigure(1, weight=1)

        top_l = ctk.CTkFrame(self.view_library, fg_color="transparent")
        top_l.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(top_l, text="STUDIO", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=TEXT_DIM, anchor="w").pack(fill="x")
        ctk.CTkLabel(top_l, text="Library", font=ctk.CTkFont(size=24, weight="bold"),
                     text_color=TEXT_MAIN, anchor="w").pack(fill="x", pady=(2, 2))
        ctk.CTkLabel(top_l, text="All clipped and captioned moments exported by BridgeClip.",
                     font=ctk.CTkFont(size=13), text_color=TEXT_MUTED, anchor="w").pack(fill="x")

        self.lib_scroll = ctk.CTkScrollableFrame(self.view_library, fg_color=CARD_BG, corner_radius=12,
                                                border_width=1, border_color=CARD_BORDER)
        self.lib_scroll.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        self.lib_scroll.grid_columnconfigure(0, weight=1)

        bot_l = ctk.CTkFrame(self.view_library, fg_color="transparent")
        bot_l.grid(row=2, column=0, sticky="ew")
        ctk.CTkButton(bot_l, text="📁 Open Output Folder", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
                      command=self.open_out).pack(side="left")
        ctk.CTkButton(bot_l, text="🔄 Refresh Library", height=38, corner_radius=8,
                      fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=12),
                      command=self._refresh_library_list).pack(side="left", padx=8)

    def _refresh_library_list(self):
        for widget in self.lib_scroll.winfo_children():
            widget.destroy()

        mp4s = glob.glob(os.path.join(OUT_DIR, "*.mp4"))
        if not mp4s:
            ctk.CTkLabel(self.lib_scroll, text="No clips generated yet.\nGo to 'Create' to find and cut your first clips!",
                         font=ctk.CTkFont(size=14), text_color=TEXT_DIM).pack(pady=60)
            return

        mp4s.sort(key=os.path.getmtime, reverse=True)
        for path in mp4s:
            name = os.path.basename(path)
            size_mb = os.path.getsize(path) / (1024 * 1024)
            card = ctk.CTkFrame(self.lib_scroll, fg_color="#12151d", corner_radius=8,
                                border_width=1, border_color="#222736")
            card.pack(fill="x", padx=10, pady=4)

            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=10)

            ctk.CTkLabel(row, text="🎬", font=ctk.CTkFont(size=20)).pack(side="left", padx=(0, 10))
            t_box = ctk.CTkFrame(row, fg_color="transparent")
            t_box.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(t_box, text=name, font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=TEXT_MAIN, anchor="w").pack(fill="x")
            ctk.CTkLabel(t_box, text="%.1f MB" % size_mb, font=ctk.CTkFont(size=11),
                         text_color=TEXT_DIM, anchor="w").pack(fill="x")

            ctk.CTkButton(row, text="Open Video", width=90, height=30, corner_radius=6,
                          fg_color=BTN_DARK, hover_color=BTN_DARK_HOVER, font=ctk.CTkFont(size=11, weight="bold"),
                          command=lambda p=path: self._open_file(p)).pack(side="right")

    def _open_file(self, filepath):
        try:
            if os.name == "nt":
                os.startfile(filepath)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", filepath])
            else:
                subprocess.Popen(["xdg-open", filepath])
        except Exception as e:
            self.log("Could not open file: %s" % e)

    # ----------------------------------------------------------------------
    # Status & Logging
    # ----------------------------------------------------------------------
    def log(self, msg):
        msg = str(msg)
        self.logq.put(msg)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
        except OSError:
            pass

    def set_status(self, text, color=None):
        self.logq.put(("status", text, color))

    def _drain(self):
        try:
            while True:
                item = self.logq.get_nowait()
                if isinstance(item, tuple):
                    _, text, color = item
                    self.jobs_status_lbl.configure(text=text, text_color=color or TEXT_MAIN)
                    self.sb_status.configure(text=" " + text[:22], text_color=color or TEXT_MUTED)
                    continue
                self.console.configure(state="normal")
                self.console.insert("end", item + "\n")
                self.console.see("end")
                self.console.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    # ----------------------------------------------------------------------
    # Actions & Execution
    # ----------------------------------------------------------------------
    def pick_file(self):
        p = filedialog.askopenfilename(
            title="Select a video",
            filetypes=[("Video files", "*.mp4 *.webm *.mkv"), ("All files", "*.*")])
        if p:
            self.src.delete(0, "end")
            self.src.insert(0, p)
            self._on_src_changed()

    def pick_dl_dir(self):
        d = filedialog.askdirectory(title="Choose download folder")
        if d:
            self.dl_dir.delete(0, "end")
            self.dl_dir.insert(0, d)

    def _open_folder(self, folder):
        os.makedirs(folder, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            self.log("Could not open folder: %s" % e)

    def open_out(self):
        self._open_folder(OUT_DIR)

    def open_videos(self):
        self._open_folder(self.dl_dir.get().strip() or VIDEOS_DIR)

    def _auto_offer(self):
        need = missing_tools()
        if need:
            self._offer_install(need)

    def install_clicked(self):
        need = missing_tools()
        if not need:
            messagebox.showinfo(APP_TITLE, "ffmpeg, ffprobe and yt-dlp are already installed.")
            return
        self._offer_install(need)

    def _offer_install(self, need):
        if self.installing or self.busy:
            return
        if os.name != "nt":
            messagebox.showerror(APP_TITLE, "Missing: %s\\n\\nInstall them with your package manager." % ", ".join(need))
            return
        if messagebox.askyesno(
                APP_TITLE,
                "BridgeClip needs these free tools: %s\\n\\nDownload and install them automatically now? (~150 MB)" % ", ".join(need)):
            self.installing = True
            self.progress.start()
            threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        ok = False
        try:
            self.set_status("Installing tools...", "#4da3ff")
            ok = install_tools(self.log, self.set_status)
        except Exception as e:
            self.log("INSTALL ERROR: %r" % (e,))
        finally:
            self.installing = False

            def done():
                self.progress.stop()
                self.progress.set(0)
            self.after(0, done)
            if ok:
                self.set_status("Tools installed - you're ready to go", "#3ddc84")
            else:
                self.set_status("Some tools are still missing - see Jobs console", "#ff6b6b")

    def check_tools(self):
        def work():
            self._set_view("Jobs")
            for tool in ("ffmpeg", "ffprobe", "yt-dlp"):
                path = shutil.which(tool)
                if not path:
                    self.log("[tools] %s: NOT FOUND" % tool)
                    continue
                ver = ""
                try:
                    flag = "--version" if tool == "yt-dlp" else "-version"
                    ver = run_capture([tool, flag]).stdout.splitlines()[0]
                except Exception:
                    pass
                self.log("[tools] %s: %s  %s" % (tool, path, ver))
        threading.Thread(target=work, daemon=True).start()

    def update_ytdlp(self):
        def work():
            self._set_view("Jobs")
            if not shutil.which("yt-dlp"):
                self.log("yt-dlp not found, nothing to update.")
                return
            self.log("Updating yt-dlp...")
            lines = []
            run_stream(["yt-dlp", "-U"], self.log, collect=lines)
            if any("pip" in l.lower() for l in lines):
                self.log("yt-dlp was installed with pip. Run:  pip install -U yt-dlp")
        threading.Thread(target=work, daemon=True).start()

    def start(self):
        if self.busy:
            return
        src = self.src.get().strip().strip('"')
        if not src:
            messagebox.showwarning(APP_TITLE, "Please paste a YouTube link or select a local video first.")
            self._set_step(0)
            return
        if not os.path.isfile(src) and not is_url(src):
            messagebox.showwarning(APP_TITLE, "That is not an existing file or a valid http(s) link.")
            self._set_step(0)
            return

        need = missing_tools()
        if not is_url(src):
            need = [t for t in need if t != "yt-dlp"]
        if need:
            self._offer_install(need)
            return

        len_map = {
            "10-30s": 25,
            "30-60s": 45,
            "1-2m": 75,
            "2-5m": 150,
            "5-10m": 300,
            "10-15m": 600,
            "15-30m": 900,
        }
        clip_len = len_map.get(self.clip_length_val, 45)

        if self.ai_decide_switch.get():
            max_clips = 5
        else:
            try:
                max_clips = max(1, int(self.max_clips_entry.get()))
            except ValueError:
                max_clips = 3

        mode_map = {
            "Quality": "Smart Mix (AI + hype + replays)",
            "Economy": "Highest Playtime (Most Replayed)",
            "Direct": "Loudest Moments (no AI)",
        }
        mode = mode_map.get(self.clipping_mode_val, "Smart Mix (AI + hype + replays)")

        framing_map = {
            "Smart": "Smart crop (follow action)",
            "Full frame": "Center crop",
            "Classic": "Blurred background fit",
        }
        framing = framing_map.get(self.framing_val, "Smart crop (follow action)")

        is_vert = self.format_val.startswith("Vertical")

        size_map_vert = {"S": 32, "M": 44, "L": 56, "XL": 70}
        size_map_horiz = {"S": 20, "M": 26, "L": 34, "XL": 44}
        cap_size_code = self.cap_size.get() or "M"
        caption_size = size_map_vert.get(cap_size_code, 44) if is_vert else size_map_horiz.get(cap_size_code, 26)

        pacing_map = {
            "Punchy (1-2 words)": 2,
            "Fast (2-3 words)": 3,
            "Balanced (3-4 words)": 4,
            "Sentence (5-7)": 6,
        }
        words_per_chunk = pacing_map.get(self.cap_pacing.get(), 3)
        lang, prompt = CAPTION_LANGS.get(self.cap_lang.get(), (None, None))

        opts = {
            "captions": bool(self.captions_switch.get()),
            "cap_style": self.caption_style_val,
            "cap_font": CAPTION_STYLES.get(self.caption_style_val, {}).get("font", "Impact"),
            "cap_pos": self.cap_pos.get(),
            "cap_words": words_per_chunk,
            "cap_upper": CAPTION_STYLES.get(self.caption_style_val, {}).get("all_caps", True),
            "caption_size": caption_size,
            "cap_lang": lang,
            "cap_prompt": prompt,
            "fade": True,
            "zoom": False,
            "normalize": True,
            "speed": self.speed_val,
            "vo_mode": "Off",
            "mode": mode,
            "cookies": self.cookies.get(),
            "dl_quality": self.dl_quality.get(),
            "dl_dir": self.dl_dir.get().strip() or VIDEOS_DIR,
            "dl_only": False,
            "snap": bool(self.snap.get()),
            "framing": framing,
            "quality": "Balanced",
        }

        set_api_key(self.api_key.get())
        save_settings(api_url=self.api.get().strip() or DEFAULT_API, api_key=API_KEY)
        args = (src, max_clips, clip_len, is_vert, self.api.get().strip() or DEFAULT_API, opts)

        self.busy = True
        self.btn_next.configure(state="disabled")
        self.progress.start()
        self.set_status("Starting job...", "#4da3ff")
        self._set_view("Jobs")

        threading.Thread(target=self._worker, args=args, daemon=True).start()

    def _finish(self):
        self.busy = False

        def reset():
            self.progress.stop()
            self.progress.set(0)
            self.btn_next.configure(state="normal")
            self._refresh_library_list()
        self.after(0, reset)

    def _worker(self, src, max_clips, clip_len, vertical, api_url, opts):
        log = self.log
        mode = opts.get("mode", "Smart Mix (AI + hype + replays)")
        ok = False
        try:
            # 1. input
            if os.path.isfile(src):
                video = src
                log("Using local file: " + video)
            else:
                self.set_status("Downloading video...", "#4da3ff")
                video = download_video(
                    src, log,
                    cookies_browser=opts.get("cookies"),
                    dl_dir=opts.get("dl_dir"),
                    quality=opts.get("dl_quality")
                )
                if not video:
                    return
                log("Downloaded: " + video)

            info = None
            info_path = os.path.splitext(video)[0] + ".info.json"
            if os.path.isfile(info_path):
                try:
                    with open(info_path, encoding="utf-8") as f:
                        info = json.load(f)
                except Exception as e:
                    log("Could not read info.json: %s" % e)

            duration = get_duration(video, info)
            log("Duration: %s" % fmt_time(duration))
            log("Mode: " + mode)

            clips = []
            a_peaks, h_peaks = [], heatmap_peaks(info)

            # 2a. highest playtime (YouTube "Most replayed")
            if "Highest Playtime" in mode:
                self.set_status("Reading replay heatmap...", "#4da3ff")
                clips = replayed_clips(info, duration, clip_len, max_clips)
                if clips:
                    log("Picked %d highest-playtime window(s) from the replay heatmap." % len(clips))
                else:
                    log("No YouTube replay heatmap for this video. Using loudest moments instead.")
                    mode = "Loudest Moments (no AI)"

            # 2b. loudest moments / smart mix
            if not clips:
                self.set_status("Scanning audio for hype...", "#4da3ff")
                a_peaks = audio_peaks(video, duration, log)
                log("Heatmap peaks: %d" % len(h_peaks) if h_peaks else "No YouTube heatmap available.")

            if not clips and "Smart Mix" in mode:
                transcript = load_transcript(video)
                log("Transcript loaded (%d chars)." % len(transcript) if transcript else "No subtitles found.")
                self.set_status("Asking AI for the best moments...", "#4da3ff")
                try:
                    base = api_base(api_url)
                    model = pick_model(base, log)
                    raw = ask_llm(base, model, duration, clip_len, max_clips,
                                  a_peaks, h_peaks, transcript, log)
                    clips = clean_clips(raw, duration, clip_len, max_clips)
                except (urllib.error.URLError, OSError, ValueError, KeyError,
                        RuntimeError, json.JSONDecodeError) as e:
                    log("LLM step failed: %s" % e)

            if not clips:
                log("Selecting loudest / hottest moments directly.")
                clips = fallback_clips(a_peaks, h_peaks, duration, clip_len, max_clips)
            if not clips:
                log("No clips could be determined.")
                return

            if opts.get("snap"):
                self.set_status("Finding clean cut points...", "#4da3ff")
                mids = detect_silences(video, log)
                clips = snap_clips(clips, mids, duration, clip_len) or clips
            log("Selected clips:\\n" + json.dumps(clips, indent=2))

            # 3. cut
            self.set_status("Cutting clips...", "#4da3ff")
            cut_clips(video, clips, vertical, log, opts, api_base(api_url))
            log("Done! Clips are in: " + OUT_DIR)
            ok = True
        except Exception as e:
            log("UNEXPECTED ERROR: %r" % e)
        finally:
            if ok:
                self.set_status("Done - clips are in output_clips", "#3ddc84")
            else:
                self.set_status("Stopped - see Jobs console for details", "#ff6b6b")
            self._finish()


if __name__ == "__main__":
    try:
        App().mainloop()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            with open(os.path.join(BASE, "hypeclipper_crash.log"), "w", encoding="utf-8") as f:
                f.write(tb)
        except OSError:
            pass
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror(APP_TITLE, "BridgeClip crashed:\\n\\n" + tb[-1500:])
        except Exception:
            pass
"""

with open(main_path, "w", encoding="utf-8") as f:
    f.write(core_logic + new_ui_code)

print("SUCCESS: main.py updated with BridgeClip Studio UI")
