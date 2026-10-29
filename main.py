import json
import os
import platform
import queue
import re
import subprocess
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog

try:
    import keyring
except ImportError:
    keyring = None

try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


APP_NAME = "J.A.R.V.I.S."
APP_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "JarvisDesktop"
APP_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = APP_DIR / "config.json"
DATA_FILE = APP_DIR / "data.json"
KEYRING_SERVICE = "JarvisDesktop"
KEYRING_USERNAME = "OPENAI_API_KEY"

DEFAULT_CONFIG = {
    "model": "gpt-5.5",
    "speech_language": "uk-UA",
    "speak_replies": True,
    "remember_history": True
}

SYSTEM_INSTRUCTIONS = """
You are J.A.R.V.I.S., a helpful desktop AI assistant. Reply in the same language
as the user, preferably Ukrainian when the user writes Ukrainian. Be clear and
practical. You do not directly control the computer: local actions are handled
only by the application's explicit allowlisted commands. Never claim that you
opened, changed, deleted, sent, or executed something unless the application
confirms that action. If asked to run a shell command or perform a risky system
change, explain what it does and ask the user to do it manually. Do not request
passwords, API keys, or other secrets in chat.
""".strip()


def load_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return fallback.copy() if isinstance(fallback, dict) else fallback


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temporary.replace(path)


class JarvisApp:
    BG = "#07111b"
    PANEL = "#0b1b28"
    PANEL_2 = "#102635"
    CYAN = "#46eaff"
    CYAN_DIM = "#168da4"
    TEXT = "#d8f7ff"
    MUTED = "#7fa6b8"
    GREEN = "#69ffbd"
    RED = "#ff7185"
    FONT = "Segoe UI"

    def __init__(self, root):
        self.root = root
        self.root.title("J.A.R.V.I.S. — Desktop AI")
        self.root.geometry("1180x780")
        self.root.minsize(900, 640)
        self.root.configure(bg=self.BG)

        self.config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
        for key, value in DEFAULT_CONFIG.items():
            self.config.setdefault(key, value)

        self.data = load_json(DATA_FILE, {"notes": [], "reminders": [], "history": []})
        self.data.setdefault("notes", [])
        self.data.setdefault("reminders", [])
        self.data.setdefault("history", [])

        self.events = queue.Queue()
        self.busy = False
        self.listening = False
        self.tts_engine = None
        self.tts_lock = threading.Lock()
        self.client = None
        self.conversation = []
        self.status_var = tk.StringVar(value="SYSTEM READY")
        self.clock_var = tk.StringVar(value="--:--:--")
        self.input_var = tk.StringVar()
        self.speech_language_var = tk.StringVar(value=self.config["speech_language"])
        self.speak_var = tk.BooleanVar(value=self.config["speak_replies"])
        self.history_var = tk.BooleanVar(value=self.config["remember_history"])

        self._build_ui()
        self._load_history()
        self._init_tts()
        self._refresh_clock()
        self._check_reminders()
        self.root.after(100, self._process_events)
        self._set_status("READY • TEXT AND VOICE AVAILABLE")
        self._system_message(
            "J.A.R.V.I.S. запущено. Напиши повідомлення або натисни MIC для голосового введення.\n"
            "Для AI-відповідей додай API key через SETTINGS. Локальні команди працюють без API."
        )

    def _build_ui(self):
        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill="x", padx=22, pady=(16, 8))

        logo = tk.Frame(header, bg=self.BG)
        logo.pack(side="left")
        tk.Label(
            logo, text="J.A.R.V.I.S.", bg=self.BG, fg=self.CYAN,
            font=(self.FONT, 25, "bold")
        ).pack(anchor="w")
        tk.Label(
            logo, text="PERSONAL AI • DESKTOP CONTROL INTERFACE",
            bg=self.BG, fg=self.MUTED, font=(self.FONT, 9, "bold")
        ).pack(anchor="w", pady=(2, 0))

        header_right = tk.Frame(header, bg=self.BG)
        header_right.pack(side="right")
        tk.Label(
            header_right, textvariable=self.clock_var, bg=self.BG, fg=self.CYAN,
            font=("Consolas", 18, "bold")
        ).pack(anchor="e")
        tk.Label(
            header_right, textvariable=self.status_var, bg=self.BG, fg=self.GREEN,
            font=(self.FONT, 9, "bold")
        ).pack(anchor="e", pady=(5, 0))

        separator = tk.Frame(self.root, bg=self.CYAN_DIM, height=1)
        separator.pack(fill="x", padx=22, pady=(4, 12))

        body = tk.Frame(self.root, bg=self.BG)
        body.pack(fill="both", expand=True, padx=22, pady=(0, 12))

        sidebar = tk.Frame(body, bg=self.PANEL, width=245, highlightbackground="#164456", highlightthickness=1)
        sidebar.pack(side="left", fill="y", padx=(0, 12))
        sidebar.pack_propagate(False)

        self._section_label(sidebar, "SYSTEM CORE").pack(anchor="w", padx=16, pady=(17, 8))
        self.reactor = tk.Canvas(sidebar, width=190, height=190, bg=self.PANEL, highlightthickness=0)
        self.reactor.pack(pady=(0, 8))
        self._draw_reactor()

        self._section_label(sidebar, "QUICK ACTIONS").pack(anchor="w", padx=16, pady=(12, 8))
        self._side_button(sidebar, "OPEN BROWSER", lambda: self._local_command("відкрий браузер"))
        self._side_button(sidebar, "OPEN NOTEPAD", lambda: self._local_command("відкрий блокнот"))
        self._side_button(sidebar, "NEW NOTE", self._new_note)
        self._side_button(sidebar, "SET REMINDER", self._new_reminder)
        self._side_button(sidebar, "SETTINGS", self._settings)

        tk.Label(
            sidebar, text="LOCAL COMMANDS WORK OFFLINE\nAI REQUIRES API ACCESS",
            bg=self.PANEL, fg=self.MUTED, justify="left",
            font=(self.FONT, 8, "bold")
        ).pack(side="bottom", anchor="w", padx=15, pady=15)

        main_panel = tk.Frame(body, bg=self.PANEL, highlightbackground="#164456", highlightthickness=1)
        main_panel.pack(side="left", fill="both", expand=True)

        topbar = tk.Frame(main_panel, bg=self.PANEL)
        topbar.pack(fill="x", padx=16, pady=(14, 8))
        self._section_label(topbar, "NEURAL INTERFACE / CONVERSATION").pack(side="left")
        tk.Button(
            topbar, text="CLEAR", command=self._clear_chat,
            bg=self.PANEL_2, fg=self.MUTED, activebackground="#17394a",
            activeforeground=self.CYAN, relief="flat", bd=0,
            font=(self.FONT, 8, "bold"), padx=12, pady=6, cursor="hand2"
        ).pack(side="right")

        chat_frame = tk.Frame(main_panel, bg=self.BG, highlightbackground="#17394a", highlightthickness=1)
        chat_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        self.chat = tk.Text(
            chat_frame, bg=self.BG, fg=self.TEXT, insertbackground=self.CYAN,
            selectbackground="#174354", wrap="word", relief="flat", bd=0,
            padx=14, pady=14, font=(self.FONT, 10), state="disabled"
        )
        scrollbar = tk.Scrollbar(chat_frame, command=self.chat.yview, bg=self.PANEL)
        self.chat.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.chat.pack(side="left", fill="both", expand=True)

        self.chat.tag_configure("user", foreground=self.CYAN, font=(self.FONT, 10, "bold"), spacing1=10)
        self.chat.tag_configure("jarvis", foreground=self.GREEN, font=(self.FONT, 10, "bold"), spacing1=10)
        self.chat.tag_configure("body", foreground=self.TEXT, lmargin1=10, lmargin2=10, spacing3=5)
        self.chat.tag_configure("system", foreground=self.MUTED, font=(self.FONT, 9, "italic"), spacing1=6, spacing3=8)

        input_panel = tk.Frame(main_panel, bg=self.PANEL)
        input_panel.pack(fill="x", padx=14, pady=(0, 14))

        self.entry = tk.Entry(
            input_panel, textvariable=self.input_var, bg="#06101a", fg=self.TEXT,
            insertbackground=self.CYAN, relief="flat", bd=0,
            font=(self.FONT, 11), highlightbackground="#1c5366",
            highlightcolor=self.CYAN, highlightthickness=1
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=12, padx=(0, 8))
        self.entry.bind("<Return>", lambda event: self._send_message())

        self.mic_button = tk.Button(
            input_panel, text="MIC", command=self._start_listening,
            bg="#123443", fg=self.CYAN, activebackground="#1b5265",
            activeforeground="white", relief="flat", bd=0,
            font=(self.FONT, 9, "bold"), padx=16, pady=11, cursor="hand2"
        )
        self.mic_button.pack(side="left", padx=(0, 8))

        self.send_button = tk.Button(
            input_panel, text="SEND", command=self._send_message,
            bg=self.CYAN_DIM, fg="white", activebackground="#20b5cc",
            activeforeground="white", relief="flat", bd=0,
            font=(self.FONT, 9, "bold"), padx=18, pady=11, cursor="hand2"
        )
        self.send_button.pack(side="left")

        footer = tk.Frame(self.root, bg=self.BG)
        footer.pack(fill="x", padx=22, pady=(0, 12))
        tk.Label(
            footer, text="JARVIS DESKTOP BUILD 1.0  •  LOCAL AUTOMATION IS ALLOWLISTED",
            bg=self.BG, fg="#456b7b", font=(self.FONT, 8)
        ).pack(side="left")
        tk.Label(
            footer, text=f"OS: {platform.system()}",
            bg=self.BG, fg="#456b7b", font=(self.FONT, 8)
        ).pack(side="right")

    def _section_label(self, parent, text):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=self.CYAN_DIM,
                        font=(self.FONT, 9, "bold"))

    def _side_button(self, parent, text, command):
        button = tk.Button(
            parent, text="›  " + text, command=command, anchor="w",
            bg=self.PANEL, fg=self.TEXT, activebackground="#123443",
            activeforeground=self.CYAN, relief="flat", bd=0,
            font=(self.FONT, 9, "bold"), padx=16, pady=9, cursor="hand2"
        )
        button.pack(fill="x", padx=6)
        return button

    def _draw_reactor(self):
        c = self.reactor
        c.delete("all")
        cx, cy = 95, 95
        for radius, color, width in [(77, "#164e62", 2), (65, self.CYAN_DIM, 2), (49, "#1b5265", 1), (34, self.CYAN, 2)]:
            c.create_oval(cx-radius, cy-radius, cx+radius, cy+radius, outline=color, width=width)
        c.create_oval(cx-24, cy-24, cx+24, cy+24, fill="#123c4b", outline=self.CYAN, width=2)
        c.create_text(cx, cy, text="AI", fill=self.CYAN, font=("Consolas", 14, "bold"))
        for angle in range(0, 360, 45):
            import math
            rad = math.radians(angle)
            x1, y1 = cx + 53 * math.cos(rad), cy + 53 * math.sin(rad)
            x2, y2 = cx + 61 * math.cos(rad), cy + 61 * math.sin(rad)
            c.create_line(x1, y1, x2, y2, fill=self.GREEN, width=2)
        c.create_text(cx, 178, text="CORE ONLINE", fill=self.GREEN, font=("Consolas", 8, "bold"))

    def _set_status(self, text, color=None):
        self.status_var.set(text)
        if color:
            for child in self.root.winfo_children():
                pass

    def _refresh_clock(self):
        self.clock_var.set(datetime.now().strftime("%H:%M:%S"))
        self.root.after(1000, self._refresh_clock)

    def _append(self, speaker, text, tag):
        self.chat.configure(state="normal")
        stamp = datetime.now().strftime("%H:%M")
        self.chat.insert("end", f"[{stamp}]  {speaker}\n", tag)
        self.chat.insert("end", text.strip() + "\n\n", "body")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _system_message(self, text):
        self.chat.configure(state="normal")
        self.chat.insert("end", text + "\n\n", "system")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _load_history(self):
        if not self.config.get("remember_history", True):
            return
        for item in self.data.get("history", [])[-40:]:
            role = item.get("role")
            content = item.get("content", "")
            if role == "user":
                self._append("YOU", content, "user")
            elif role == "assistant":
                self._append("J.A.R.V.I.S.", content, "jarvis")

    def _save_history_item(self, role, content):
        if not self.config.get("remember_history", True):
            return
        self.data.setdefault("history", []).append({
            "role": role,
            "content": content,
            "time": datetime.now().isoformat(timespec="seconds")
        })
        self.data["history"] = self.data["history"][-100:]
        save_json(DATA_FILE, self.data)

    def _clear_chat(self):
        if not messagebox.askyesno("Clear conversation", "Clear the visible conversation and saved chat history?"):
            return
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self.data["history"] = []
        self.conversation = []
        save_json(DATA_FILE, self.data)
        self._system_message("Conversation cleared.")

    def _get_api_key(self):
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if key:
            return key
        if keyring:
            try:
                return (keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME) or "").strip()
            except Exception:
                return ""
        return ""

    def _settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("JARVIS Settings")
        dialog.configure(bg=self.PANEL)
        dialog.geometry("500x390")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="SYSTEM SETTINGS", bg=self.PANEL, fg=self.CYAN,
                 font=(self.FONT, 15, "bold")).pack(anchor="w", padx=22, pady=(20, 15))

        tk.Label(dialog, text="OpenAI model", bg=self.PANEL, fg=self.TEXT,
                 font=(self.FONT, 9, "bold")).pack(anchor="w", padx=22)
        model_var = tk.StringVar(value=self.config.get("model", "gpt-5.5"))
        tk.Entry(dialog, textvariable=model_var, bg=self.BG, fg=self.TEXT,
                 insertbackground=self.CYAN, relief="flat").pack(fill="x", padx=22, pady=(5, 12), ipady=7)

        tk.Label(dialog, text="API key (stored in Windows Credential Manager when available)",
                 bg=self.PANEL, fg=self.TEXT, font=(self.FONT, 9, "bold")).pack(anchor="w", padx=22)
        key_var = tk.StringVar()
        key_entry = tk.Entry(dialog, textvariable=key_var, show="•", bg=self.BG, fg=self.TEXT,
                             insertbackground=self.CYAN, relief="flat")
        key_entry.pack(fill="x", padx=22, pady=(5, 5), ipady=7)
        tk.Label(dialog, text="Leave blank to keep the current key or use OPENAI_API_KEY.",
                 bg=self.PANEL, fg=self.MUTED, font=(self.FONT, 8)).pack(anchor="w", padx=22, pady=(0, 12))

        speech_var = tk.StringVar(value=self.config.get("speech_language", "uk-UA"))
        tk.Label(dialog, text="Speech recognition language", bg=self.PANEL, fg=self.TEXT,
                 font=(self.FONT, 9, "bold")).pack(anchor="w", padx=22)
        tk.OptionMenu(dialog, speech_var, "uk-UA", "en-US", "cs-CZ").pack(anchor="w", padx=22, pady=(4, 8))

        speak_var = tk.BooleanVar(value=self.config.get("speak_replies", True))
        history_var = tk.BooleanVar(value=self.config.get("remember_history", True))
        tk.Checkbutton(dialog, text="Speak assistant replies", variable=speak_var,
                       bg=self.PANEL, fg=self.TEXT, selectcolor=self.BG, activebackground=self.PANEL,
                       activeforeground=self.CYAN).pack(anchor="w", padx=22)
        tk.Checkbutton(dialog, text="Save conversation history locally", variable=history_var,
                       bg=self.PANEL, fg=self.TEXT, selectcolor=self.BG, activebackground=self.PANEL,
                       activeforeground=self.CYAN).pack(anchor="w", padx=22)

        def save_settings():
            model = model_var.get().strip()
            if not model:
                messagebox.showerror("Invalid setting", "Model name cannot be empty.", parent=dialog)
                return
            self.config["model"] = model
            self.config["speech_language"] = speech_var.get()
            self.config["speak_replies"] = speak_var.get()
            self.config["remember_history"] = history_var.get()
            self.speech_language_var.set(speech_var.get())
            self.speak_var.set(speak_var.get())
            self.history_var.set(history_var.get())
            new_key = key_var.get().strip()
            if new_key:
                if keyring:
                    try:
                        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, new_key)
                    except Exception as exc:
                        messagebox.showerror(
                            "Key storage error",
                            f"Could not store key in Windows Credential Manager:\n{exc}\n\n"
                            "Install keyring or set OPENAI_API_KEY in Windows environment variables.",
                            parent=dialog
                        )
                        return
                else:
                    messagebox.showerror(
                        "Key storage unavailable",
                        "The keyring package is missing. Install requirements.txt or set OPENAI_API_KEY.",
                        parent=dialog
                    )
                    return
            save_json(CONFIG_FILE, self.config)
            self._system_message("Settings saved.")
            dialog.destroy()

        tk.Button(dialog, text="SAVE SETTINGS", command=save_settings, bg=self.CYAN_DIM, fg="white",
                  activebackground="#20b5cc", relief="flat", bd=0,
                  font=(self.FONT, 9, "bold"), padx=16, pady=9).pack(anchor="e", padx=22, pady=16)

    def _init_tts(self):
        if pyttsx3 is None:
            return
        def initialize():
            try:
                self.tts_engine = pyttsx3.init()
                self.tts_engine.setProperty("rate", 180)
            except Exception:
                self.tts_engine = None
        threading.Thread(target=initialize, daemon=True).start()

    def _speak(self, text):
        if not self.config.get("speak_replies", True) or pyttsx3 is None:
            return
        def worker():
            with self.tts_lock:
                try:
                    if self.tts_engine is None:
                        self.tts_engine = pyttsx3.init()
                    self.tts_engine.say(text[:1500])
                    self.tts_engine.runAndWait()
                except Exception as exc:
                    self.events.put(("status", f"VOICE OUTPUT UNAVAILABLE: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _start_listening(self):
        if self.listening:
            return
        if sr is None:
            messagebox.showerror(
                "Voice input unavailable",
                "SpeechRecognition is not installed. Run: pip install -r requirements.txt"
            )
            return
        self.listening = True
        self.mic_button.configure(text="LISTENING…", state="disabled")
        self._set_status("LISTENING • SPEAK NOW")
        threading.Thread(target=self._listen_worker, daemon=True).start()

    def _listen_worker(self):
        try:
            recognizer = sr.Recognizer()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.6)
                audio = recognizer.listen(source, timeout=6, phrase_time_limit=15)
            text = recognizer.recognize_google(audio, language=self.config.get("speech_language", "uk-UA"))
            self.events.put(("recognized", text))
        except Exception as exc:
            self.events.put(("voice_error", str(exc)))
        finally:
            self.events.put(("listening_done", None))

    def _process_events(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "recognized":
                    self.input_var.set(payload)
                    self._send_message()
                elif event == "voice_error":
                    self._system_message(f"Voice input error: {payload}")
                    self._set_status("VOICE INPUT ERROR")
                elif event == "listening_done":
                    self.listening = False
                    self.mic_button.configure(text="MIC", state="normal")
                    if not self.busy:
                        self._set_status("READY")
                elif event == "reply":
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.entry.configure(state="normal")
                    self._append("J.A.R.V.I.S.", payload, "jarvis")
                    self._save_history_item("assistant", payload)
                    self._speak(payload)
                    self._set_status("READY • RESPONSE RECEIVED")
                elif event == "error":
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.entry.configure(state="normal")
                    self._append("J.A.R.V.I.S.", payload, "jarvis")
                    self._set_status("REQUEST FAILED")
                elif event == "status":
                    self._set_status(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def _send_message(self):
        if self.busy:
            return
        text = self.input_var.get().strip()
        if not text:
            return
        self.input_var.set("")
        self._append("YOU", text, "user")
        self._save_history_item("user", text)

        if self._local_command(text):
            return

        self.busy = True
        self.send_button.configure(state="disabled")
        self.entry.configure(state="disabled")
        self._set_status("CONTACTING AI • PLEASE WAIT")
        threading.Thread(target=self._ask_ai_worker, args=(text,), daemon=True).start()

    def _ask_ai_worker(self, user_text):
        try:
            if OpenAI is None:
                raise RuntimeError("OpenAI SDK is not installed. Run: pip install -r requirements.txt")
            api_key = self._get_api_key()
            if not api_key:
                raise RuntimeError(
                    "API key is not configured. Open SETTINGS and add your OpenAI API key. "
                    "Local commands still work without AI."
                )
            client = OpenAI(api_key=api_key, timeout=60.0, max_retries=2)
            self.conversation.append({"role": "user", "content": user_text})
            self.conversation = self.conversation[-20:]
            response = client.responses.create(
                model=self.config.get("model", "gpt-5.5"),
                instructions=SYSTEM_INSTRUCTIONS,
                input=self.conversation,
                max_output_tokens=1200
            )
            answer = (response.output_text or "").strip()
            if not answer:
                answer = "The AI returned an empty response. Please try again."
            self.conversation.append({"role": "assistant", "content": answer})
            self.conversation = self.conversation[-20:]
            self.events.put(("reply", answer))
        except Exception as exc:
            self.events.put(("error", f"Не вдалося отримати відповідь від AI.\n{exc}"))

    def _local_command(self, raw_text):
        text = raw_text.lower().strip()
        normalized = re.sub(r"[!?.,]", "", text)

        if normalized in {"help", "допомога", "що ти вмієш", "what can you do"}:
            self._append("J.A.R.V.I.S.", self._help_text(), "jarvis")
            self._speak("Я можу відкривати програми та сайти, шукати файли, створювати нотатки й нагадування.")
            return True

        if any(phrase in normalized for phrase in ["котра година", "яка година", "what time is it", "current time"]):
            self._local_reply(f"Зараз {datetime.now().strftime('%H:%M:%S')}.")
            return True

        if any(phrase in normalized for phrase in ["яка сьогодні дата", "яке сьогодні число", "today's date", "what is the date"]):
            self._local_reply(f"Сьогодні {datetime.now().strftime('%d.%m.%Y')}.")
            return True

        if any(phrase in normalized for phrase in ["відкрий браузер", "open browser", "відкрий google", "open google"]):
            webbrowser.open("https://www.google.com")
            self._local_reply("Відкрив Google у браузері за замовчуванням.")
            return True

        if any(phrase in normalized for phrase in ["відкрий youtube", "open youtube"]):
            webbrowser.open("https://www.youtube.com")
            self._local_reply("Відкрив YouTube у браузері.")
            return True

        if any(phrase in normalized for phrase in ["відкрий github", "open github"]):
            webbrowser.open("https://github.com")
            self._local_reply("Відкрив GitHub у браузері.")
            return True

        if any(phrase in normalized for phrase in ["відкрий блокнот", "open notepad", "запусти блокнот"]):
            try:
                subprocess.Popen(["notepad.exe"])
                self._local_reply("Блокнот запущено.")
            except Exception as exc:
                self._local_reply(f"Не вдалося запустити Блокнот: {exc}")
            return True

        if any(phrase in normalized for phrase in ["відкрий калькулятор", "open calculator", "запусти калькулятор"]):
            try:
                subprocess.Popen(["calc.exe"])
                self._local_reply("Калькулятор запущено.")
            except Exception as exc:
                self._local_reply(f"Не вдалося запустити калькулятор: {exc}")
            return True

        if normalized.startswith("пошук в інтернеті ") or normalized.startswith("search the web for "):
            query = raw_text.split(" ", 3)[-1].strip()
            if query:
                webbrowser.open("https://www.google.com/search?q=" + __import__("urllib.parse").parse.quote(query))
                self._local_reply(f"Відкрив пошук у браузері: {query}")
            else:
                self._local_reply("Напиши, що саме потрібно знайти.")
            return True

        if normalized.startswith("знайди файл ") or normalized.startswith("find file "):
            query = raw_text.split(" ", 2)[-1].strip()
            self._search_files(query)
            return True

        if normalized.startswith("нотатка ") or normalized.startswith("note "):
            note = raw_text.split(" ", 1)[-1].strip()
            if note:
                self.data.setdefault("notes", []).append({
                    "text": note,
                    "created": datetime.now().isoformat(timespec="seconds")
                })
                save_json(DATA_FILE, self.data)
                self._local_reply("Нотатку збережено локально.")
            else:
                self._local_reply("Після слова «нотатка» додай текст.")
            return True

        reminder_match = re.match(
            r"^(?:нагадай|remind me)\s+(?:через\s+)?(\d+)\s*(секунд(?:у|и)?|сек|хвилин(?:у|и)?|хв|годин(?:у|и)?|год|second(?:s)?|minute(?:s)?|hour(?:s)?)\s+(?:що\s+|to\s+)?(.+)$",
            raw_text.strip(), re.IGNORECASE
        )
        if reminder_match:
            amount = int(reminder_match.group(1))
            unit = reminder_match.group(2).lower()
            message = reminder_match.group(3).strip()
            if amount < 1 or amount > 10080:
                self._local_reply("Вкажи інтервал від 1 до 10080 одиниць часу.")
                return True
            if unit.startswith(("сек", "second")):
                delta = timedelta(seconds=amount)
            elif unit.startswith(("хв", "minute")):
                delta = timedelta(minutes=amount)
            else:
                delta = timedelta(hours=amount)
            due = datetime.now() + delta
            self.data.setdefault("reminders", []).append({
                "message": message,
                "due": due.isoformat(timespec="seconds"),
                "done": False
            })
            save_json(DATA_FILE, self.data)
            self._local_reply(f"Нагадування збережено на {due.strftime('%d.%m.%Y о %H:%M:%S')}: {message}")
            return True

        if normalized in {"покажи нотатки", "show notes", "мої нотатки"}:
            notes = self.data.get("notes", [])
            if not notes:
                self._local_reply("Збережених нотаток поки немає.")
            else:
                self._local_reply("Твої нотатки:\n" + "\n".join(
                    f"{i}. {item['text']}" for i, item in enumerate(notes[-20:], 1)
                ))
            return True

        if normalized in {"покажи нагадування", "show reminders", "мої нагадування"}:
            reminders = [r for r in self.data.get("reminders", []) if not r.get("done")]
            if not reminders:
                self._local_reply("Активних нагадувань немає.")
            else:
                self._local_reply("Активні нагадування:\n" + "\n".join(
                    f"{i}. {r['due'].replace('T', ' ')} — {r['message']}"
                    for i, r in enumerate(reminders, 1)
                ))
            return True

        if normalized in {"інформація про систему", "system information", "характеристики комп'ютера"}:
            self._local_reply(
                f"ОС: {platform.system()} {platform.release()}\n"
                f"Версія Python: {platform.python_version()}\n"
                f"Архітектура: {platform.machine()}\n"
                f"Комп'ютер: {platform.node()}"
            )
            return True

        return False

    def _local_reply(self, text):
        self._append("J.A.R.V.I.S.", text, "jarvis")
        self._save_history_item("assistant", text)
        self._speak(text)
        self._set_status("LOCAL ACTION COMPLETED")

    def _help_text(self):
        return (
            "Доступні локальні команди:\n"
            "• відкрий браузер / YouTube / GitHub\n"
            "• відкрий блокнот / калькулятор\n"
            "• котра година / яка сьогодні дата\n"
            "• пошук в інтернеті Python tutorial\n"
            "• знайди файл report.pdf\n"
            "• нотатка Купити зошит\n"
            "• нагадай через 10 хвилин перевірити завдання\n"
            "• покажи нотатки / покажи нагадування\n"
            "• інформація про систему\n\n"
            "Інші запити надсилаються до AI та потребують API key."
        )

    def _search_files(self, query):
        if not query:
            self._local_reply("Вкажи ім'я або частину імені файлу.")
            return
        home = Path.home()
        ignored = {"AppData", ".git", "node_modules", ".venv", "venv", "__pycache__"}
        matches = []
        needle = query.casefold()
        try:
            for current, dirs, files in os.walk(home):
                dirs[:] = [d for d in dirs if d not in ignored]
                depth = len(Path(current).relative_to(home).parts)
                if depth > 5:
                    dirs[:] = []
                    continue
                for filename in files:
                    if needle in filename.casefold():
                        matches.append(str(Path(current) / filename))
                        if len(matches) >= 15:
                            break
                if len(matches) >= 15:
                    break
        except (OSError, PermissionError):
            pass
        if matches:
            self._local_reply("Знайдені файли (до 15 результатів):\n" + "\n".join(matches))
        else:
            self._local_reply("Файлів із таким фрагментом імені не знайдено в доступних папках користувача.")

    def _new_note(self):
        note = simpledialog.askstring("New note", "Текст нотатки:", parent=self.root)
        if note and note.strip():
            self.data.setdefault("notes", []).append({
                "text": note.strip(),
                "created": datetime.now().isoformat(timespec="seconds")
            })
            save_json(DATA_FILE, self.data)
            self._local_reply("Нотатку збережено локально.")

    def _new_reminder(self):
        message = simpledialog.askstring("New reminder", "Про що нагадати?", parent=self.root)
        if not message or not message.strip():
            return
        minutes = simpledialog.askinteger("New reminder", "Через скільки хвилин?", minvalue=1, maxvalue=10080, parent=self.root)
        if not minutes:
            return
        due = datetime.now() + timedelta(minutes=minutes)
        self.data.setdefault("reminders", []).append({
            "message": message.strip(),
            "due": due.isoformat(timespec="seconds"),
            "done": False
        })
        save_json(DATA_FILE, self.data)
        self._local_reply(f"Нагадування встановлено на {due.strftime('%d.%m.%Y о %H:%M')}.")

    def _check_reminders(self):
        now = datetime.now()
        changed = False
        for reminder in self.data.get("reminders", []):
            if reminder.get("done"):
                continue
            try:
                due = datetime.fromisoformat(reminder["due"])
            except (ValueError, KeyError):
                reminder["done"] = True
                changed = True
                continue
            if due <= now:
                reminder["done"] = True
                changed = True
                message = reminder.get("message", "Нагадування")
                self.root.after(0, lambda m=message: self._show_reminder(m))
        if changed:
            save_json(DATA_FILE, self.data)
        self.root.after(15000, self._check_reminders)

    def _show_reminder(self, message):
        self.root.bell()
        messagebox.showinfo("J.A.R.V.I.S. Reminder", message, parent=self.root)
        self._system_message(f"REMINDER: {message}")
        self._speak(f"Нагадування. {message}")

    def _on_close(self):
        save_json(CONFIG_FILE, self.config)
        save_json(DATA_FILE, self.data)
        self.root.destroy()


def main():
    root = tk.Tk()
    app = JarvisApp(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
