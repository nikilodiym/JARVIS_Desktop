# J.A.R.V.I.S. Desktop

A Windows desktop AI assistant built with Python and Tkinter. It has a dark HUD-style interface, text chat, optional microphone input, optional speech output, OpenAI Responses API integration, and allowlisted local commands.

## Requirements

- Windows 10/11
- Python 3.10 or newer
- Internet access for AI responses and Google speech recognition
- OpenAI API key for AI chat (API billing/usage limits may apply)
- Microphone for voice input

## Quick start

1. Install Python from https://www.python.org/downloads/ and enable "Add Python to PATH".
2. Extract this folder.
3. Double-click `launch.bat`.
4. In the app, open **SETTINGS**, enter your OpenAI API key, choose a model available to your API account, and save.
5. Try a local command such as `відкрий блокнот`, or ask an AI question.

`launch.bat` creates `.venv`, installs dependencies, and starts the app. PyAudio installation can fail on some Python/platform combinations; if that happens, text chat and local commands can still be used, but microphone input will not work until PyAudio is installed.

## Manual setup

Open PowerShell in this folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

If PowerShell blocks activation, use Command Prompt and run:

```bat
.venv\Scripts\activate.bat
```

## API key

The app first checks the `OPENAI_API_KEY` environment variable. Otherwise it uses Windows Credential Manager through `keyring`. Enter the key in **SETTINGS** to save it securely where supported.

You can also set a user environment variable in PowerShell:

```powershell
setx OPENAI_API_KEY "YOUR_API_KEY_HERE"
```

Then close and reopen the terminal/app. Never commit your API key to Git or share it in screenshots. A ChatGPT subscription does not automatically include API usage; check your API account's billing and limits.

## Supported local commands

Commands are matched explicitly by the app; arbitrary text is never executed as a shell command.

- `відкрий браузер`, `відкрий YouTube`, `відкрий GitHub`
- `відкрий блокнот`, `відкрий калькулятор`
- `котра година`, `яка сьогодні дата`
- `пошук в інтернеті Python tutorial`
- `знайди файл report.pdf`
- `нотатка Купити зошит`
- `нагадай через 10 хвилин перевірити завдання`
- `покажи нотатки`, `покажи нагадування`
- `інформація про систему`
- `help` / `допомога`

English alternatives are implemented for many common commands. The reminder parser supports seconds, minutes and hours, and reminders are checked while the app is running. This is not a background Windows service; reminders will not pop up while the app is closed.

## Voice

Press **MIC**, allow microphone access if Windows asks, and speak. Speech recognition uses the Google Web Speech endpoint via `SpeechRecognition`, so voice input needs internet. Language can be changed in Settings (`uk-UA`, `en-US`, `cs-CZ`). Speech output uses installed Windows voices through `pyttsx3`; voice/language quality depends on the voices installed in Windows.

## Data and privacy

- Settings and notes are stored under `%APPDATA%\JarvisDesktop`.
- Chat history can be disabled in Settings.
- API prompts are sent to the configured AI provider.
- Voice clips are sent to Google's speech recognition service for transcription.
- File search scans the user's home folder, skips common heavy folders, and returns at most 15 matching paths.
- The app does not run arbitrary shell commands, delete files, send messages, or perform destructive system actions.

## Troubleshooting

- **AI error / missing key:** Open Settings and configure an API key. Ensure the selected model is available to your API account.
- **Microphone error:** Check Windows Settings → Privacy & security → Microphone. Ensure a working input device is selected.
- **PyAudio install fails:** Try Python 3.11 or 3.12 on Windows, then recreate `.venv` and install requirements. Text chat and local commands do not depend on PyAudio at runtime.
- **No Ukrainian voice:** Install a Ukrainian speech voice in Windows language settings. `pyttsx3` can only use voices available to the Windows speech engine.
